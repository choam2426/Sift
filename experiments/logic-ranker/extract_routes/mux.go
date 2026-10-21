package main

import (
	"fmt"
	"go/ast"
	"go/token"
	"strconv"
	"strings"
)

// chainInfo is the result of walking a router call chain such as
// r.Path("/x").Methods("GET").HandlerFunc(h) or
// r.PathPrefix("/api").Subrouter().
type chainInfo struct {
	base        ast.Expr
	path        string
	methods     []string
	handler     ast.Expr
	isSubrouter bool
}

func parseMuxChain(e ast.Expr, svars map[string]string) chainInfo {
	call, ok := e.(*ast.CallExpr)
	if !ok {
		return chainInfo{base: e}
	}
	sel, ok := call.Fun.(*ast.SelectorExpr)
	if !ok {
		return chainInfo{base: e}
	}
	info := parseMuxChain(sel.X, svars)
	switch sel.Sel.Name {
	case "Methods":
		for _, a := range call.Args {
			if s := stringValue(a, svars); s != "" {
				info.methods = append(info.methods, normalizeMethod(s))
			}
		}
	case "HandlerFunc", "Handler":
		if len(call.Args) > 0 {
			info.handler = call.Args[len(call.Args)-1]
		}
	case "Path", "PathPrefix":
		if len(call.Args) > 0 {
			info.path = stringValue(call.Args[0], svars)
		}
	case "HandleFunc":
		if len(call.Args) >= 2 {
			info.path = stringValue(call.Args[0], svars)
			info.handler = call.Args[len(call.Args)-1]
		}
	case "Subrouter":
		info.isSubrouter = true
	}
	return info
}

func identName(e ast.Expr) (string, bool) {
	switch x := e.(type) {
	case *ast.Ident:
		return x.Name, true
	case *ast.SelectorExpr:
		return x.Sel.Name, true
	}
	return "", false
}

func stringValue(e ast.Expr, svars map[string]string) string {
	switch x := e.(type) {
	case *ast.BasicLit:
		if x.Kind == token.STRING {
			if s, err := strconv.Unquote(x.Value); err == nil {
				return s
			}
		}
	case *ast.Ident:
		return svars[x.Name]
	case *ast.BinaryExpr:
		if x.Op == token.ADD {
			return stringValue(x.X, svars) + stringValue(x.Y, svars)
		}
	case *ast.ParenExpr:
		return stringValue(x.X, svars)
	}
	return ""
}

func stringVars(fd *ast.FuncDecl) map[string]string {
	m := map[string]string{}
	ast.Inspect(fd.Body, func(n ast.Node) bool {
		as, ok := n.(*ast.AssignStmt)
		if !ok || len(as.Lhs) != 1 || len(as.Rhs) != 1 {
			return true
		}
		id, ok := as.Lhs[0].(*ast.Ident)
		if !ok {
			return true
		}
		if s := stringValue(as.Rhs[0], m); s != "" {
			m[id.Name] = s
		}
		return true
	})
	return m
}

func isGroupType(name string) bool {
	switch name {
	case "RouterGroup", "Group", "Router", "IRouter":
		return true
	}
	return false
}

func joinRoute(prefix, p string) string {
	if p == "" {
		return prefix
	}
	if prefix == "" {
		return p
	}
	if p == prefix || strings.HasPrefix(p, strings.TrimRight(prefix, "/")+"/") {
		return p
	}
	return strings.TrimRight(prefix, "/") + "/" + strings.TrimLeft(p, "/")
}

func muxGroupFromCall(call *ast.CallExpr, groups map[string]groupCtx, svars map[string]string, src []byte) (groupCtx, bool) {
	info := parseMuxChain(call, svars)
	if !info.isSubrouter {
		return groupCtx{}, false
	}
	base, ok := identName(info.base)
	if !ok {
		return groupCtx{}, false
	}
	parent := groups[base]
	return groupCtx{
		path:   joinRoute(parent.path, info.path),
		source: sourceOf(call, src),
		mw:     parent.mw,
	}, true
}

func muxRoutesFromCall(call *ast.CallExpr, rel string, src []byte, groups map[string]groupCtx, vars map[string]string, svars map[string]string) []Route {
	info := parseMuxChain(call, svars)
	if info.handler == nil || info.isSubrouter {
		return nil
	}
	base, ok := identName(info.base)
	if !ok {
		return nil
	}
	g, ok := groups[base]
	if !ok {
		return nil
	}
	p := joinRoute(g.path, info.path)
	if p == "" {
		return nil
	}
	methods := info.methods
	if len(methods) == 0 {
		methods = []string{"ANY"}
	}
	ids := resolveWithVars(info.handler, rel, vars)
	hname := "inline"
	if len(ids) > 0 {
		hname = ids[0]
	}
	var out []Route
	for _, method := range methods {
		r := Route{ID: "route:" + method + " " + p, Method: method, Path: p, Handler: hname}
		parts := []string{fmt.Sprintf("Route: %s %s\nRegistration:\n%s", method, p, sourceOf(call, src))}
		if g.source != "" {
			parts = append(parts, "Group context:\n"+g.source)
		}
		for _, m := range g.mw {
			parts = append(parts, "Middleware expression:\n"+sourceOf(m, src))
			for _, id := range resolveWithVars(m, rel, vars) {
				addFunc(&parts, &r.Members, id, 2)
			}
		}
		if len(ids) > 0 {
			addFunc(&parts, &r.Members, ids[0], 2)
		} else {
			parts = append(parts, "Handler:\n"+sourceOf(info.handler, src))
		}
		for _, id := range ids {
			if fn := funcs[id]; fn != nil {
				for _, fid := range fieldCalls(fn.Source, rel) {
					addFunc(&parts, &r.Members, fid, 2)
				}
			}
		}
		text := strings.Join(parts, "\n\n")
		if len(text) > 80000 {
			text = text[:80000]
			r.Truncated = true
		}
		r.Text = text
		r.Chars = len(text)
		out = append(out, r)
	}
	return out
}

func helperPrefix(call *ast.CallExpr, groups map[string]groupCtx, svars map[string]string, src []byte) string {
	for _, arg := range call.Args {
		if c, ok := arg.(*ast.CallExpr); ok {
			if sel, ok := c.Fun.(*ast.SelectorExpr); ok && sel.Sel.Name == "Group" {
				return groupFromCall(c, groups, svars, src).path
			}
		}
		if id, ok := arg.(*ast.Ident); ok {
			if g, ok := groups[id.Name]; ok {
				return g.path
			}
		}
		if s, ok := arg.(*ast.BasicLit); ok {
			if v, err := strconv.Unquote(s.Value); err == nil {
				return v
			}
		}
	}
	return ""
}

func helperRoutesForCall(call *ast.CallExpr, rel string, src []byte, templates map[string][]Route, groups map[string]groupCtx, svars map[string]string) []Route {
	name, ok := identName(call.Fun)
	if !ok {
		return nil
	}
	prefix := helperPrefix(call, groups, svars, src)
	if prefix == "" {
		return nil
	}
	var out []Route
	for _, id := range byName[name] {
		for _, t := range templates[id] {
			p := joinRoute(prefix, t.Path)
			r := t
			r.Path = p
			r.ID = "route:" + t.Method + " " + p
			r.Text = fmt.Sprintf("Helper call:\n%s\n\n%s", sourceOf(call, src), t.Text)
			out = append(out, r)
		}
	}
	return out
}
