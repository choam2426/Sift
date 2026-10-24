package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type Func struct {
	ID, Pkg, Recv, Name, File, Source string
	Line                              int
	Calls                             []string
}
type Route struct {
	ID, Method, Path, Handler string
	Members                   []string
	Chars                     int
	Text                      string
	Truncated                 bool
	Owner                     string `json:"-"`
	Helper                    bool   `json:"-"`
}
type groupCtx struct {
	path, source, kind string
	mw                 []ast.Expr
}

var fset *token.FileSet
var funcs map[string]*Func
var byName map[string][]string
var types map[string]map[string]string
var fieldMap map[string][]string
var srcs map[string][]byte
var routeDepth = 2

func main() {
	root := flag.String("root", ".", "project root")
	out := flag.String("out", ".", "output dir")
	depth := flag.Int("depth", 2, "callee depth inside an AST route unit")
	flag.Parse()
	routeDepth = *depth
	fset = token.NewFileSet()
	funcs = map[string]*Func{}
	byName = map[string][]string{}
	types = map[string]map[string]string{}
	fieldMap = map[string][]string{}
	srcs = map[string][]byte{}
	var files []string
	_ = filepath.WalkDir(*root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			b := d.Name()
			if b == ".git" || b == "vendor" || b == "node_modules" || b == "frontend" || b == "dist" || b == "testdata" {
				return filepath.SkipDir
			}
			return nil
		}
		if strings.HasSuffix(path, ".go") && !strings.HasSuffix(path, "_test.go") {
			files = append(files, path)
		}
		return nil
	})
	// pass 1: parse functions/types
	for _, path := range files {
		src, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		srcs[path] = src
		rel, _ := filepath.Rel(*root, filepath.Dir(path))
		rel = filepath.ToSlash(rel)
		f, err := parser.ParseFile(fset, path, src, parser.ParseComments)
		if err != nil {
			continue
		}
		if types[rel] == nil {
			types[rel] = map[string]string{}
		}
		for _, decl := range f.Decls {
			if gd, ok := decl.(*ast.GenDecl); ok && gd.Tok == token.TYPE {
				for _, sp := range gd.Specs {
					if ts, ok := sp.(*ast.TypeSpec); ok {
						start := fset.Position(ts.Pos()).Offset
						end := fset.Position(ts.End()).Offset
						if start >= 0 && end <= len(src) {
							types[rel][ts.Name.Name] = string(src[start:end])
						}
					}
				}
			}
			fd, ok := decl.(*ast.FuncDecl)
			if !ok || fd.Body == nil {
				continue
			}
			recv := ""
			if fd.Recv != nil && len(fd.Recv.List) > 0 {
				t := fd.Recv.List[0].Type
				if st, ok := t.(*ast.StarExpr); ok {
					t = st.X
				}
				if id, ok := t.(*ast.Ident); ok {
					recv = id.Name
				}
			}
			id := rel + "." + fd.Name.Name
			if recv != "" {
				id = rel + "." + recv + "." + fd.Name.Name
			}
			start := fset.Position(fd.Pos()).Offset
			end := fset.Position(fd.End()).Offset
			if start < 0 || end > len(src) {
				continue
			}
			calls := map[string]bool{}
			ast.Inspect(fd.Body, func(n ast.Node) bool {
				if c, ok := n.(*ast.CallExpr); ok {
					switch f := c.Fun.(type) {
					case *ast.Ident:
						calls[f.Name] = true
					case *ast.SelectorExpr:
						calls[f.Sel.Name] = true
					}
				}
				return true
			})
			cs := []string{}
			for c := range calls {
				cs = append(cs, c)
			}
			sort.Strings(cs)
			fn := &Func{ID: id, Pkg: rel, Recv: recv, Name: fd.Name.Name, File: path, Line: fset.Position(fd.Pos()).Line, Source: string(src[start:end]), Calls: cs}
			funcs[id] = fn
			byName[fn.Name] = append(byName[fn.Name], id)
		}
	}
	// field map: Type.field -> resolved function ids from composite literals
	for _, path := range files {
		src := srcs[path]
		f, err := parser.ParseFile(fset, path, src, 0)
		if err != nil {
			continue
		}
		rel, _ := filepath.Rel(*root, filepath.Dir(path))
		rel = filepath.ToSlash(rel)
		ast.Inspect(f, func(n ast.Node) bool {
			cl, ok := n.(*ast.CompositeLit)
			if !ok {
				return true
			}
			tn := typeName(cl.Type)
			if tn == "" {
				return true
			}
			for _, elt := range cl.Elts {
				kv, ok := elt.(*ast.KeyValueExpr)
				if !ok {
					continue
				}
				key, ok := kv.Key.(*ast.Ident)
				if !ok {
					continue
				}
				ids := resolve(kv.Value, rel)
				if len(ids) > 0 {
					fieldMap[tn+"."+key.Name] = append(fieldMap[tn+"."+key.Name], ids...)
				}
			}
			return true
		})
	}
	// pass 2: routes
	var routes []Route
	helperTemplates := map[string][]Route{}
	for _, path := range files {
		src := srcs[path]
		f, err := parser.ParseFile(fset, path, src, 0)
		if err != nil {
			continue
		}
		rel, _ := filepath.Rel(*root, filepath.Dir(path))
		rel = filepath.ToSlash(rel)
		for _, decl := range f.Decls {
			fd, ok := decl.(*ast.FuncDecl)
			if !ok || fd.Body == nil {
				continue
			}
			recv := ""
			if fd.Recv != nil && len(fd.Recv.List) > 0 {
				t := fd.Recv.List[0].Type
				if st, ok := t.(*ast.StarExpr); ok {
					t = st.X
				}
				if id, ok := t.(*ast.Ident); ok {
					recv = id.Name
				}
			}
			owner := rel + "." + fd.Name.Name
			if recv != "" {
				owner = rel + "." + recv + "." + fd.Name.Name
			}
			groups := map[string]groupCtx{}
			vars := varTypes(fd)
			svars := stringVars(fd)
			innerCalls := map[*ast.CallExpr]bool{}
			ast.Inspect(fd.Body, func(n ast.Node) bool {
				if sel, ok := n.(*ast.SelectorExpr); ok {
					if c, ok := sel.X.(*ast.CallExpr); ok {
						innerCalls[c] = true
					}
				}
				return true
			})
			hasGroupParam := false
			if fd.Type.Params != nil {
				for _, f := range fd.Type.Params.List {
					tn := typeName(f.Type)
					if isGroupType(tn) {
						hasGroupParam = true
						for _, n := range f.Names {
							groups[n.Name] = groupCtx{kind: kindFromType(tn)}
						}
					}
				}
			}
			emit := func(r Route) {
				r.Owner = owner
				if hasGroupParam {
					r.Helper = true
					helperTemplates[owner] = append(helperTemplates[owner], r)
				} else {
					routes = append(routes, r)
				}
			}
			ast.Inspect(fd.Body, func(n ast.Node) bool {
				switch x := n.(type) {
				case *ast.AssignStmt:
					if len(x.Lhs) == 1 && len(x.Rhs) == 1 {
						if id, ok := x.Lhs[0].(*ast.Ident); ok {
							if call, ok := x.Rhs[0].(*ast.CallExpr); ok {
								if sel, ok := call.Fun.(*ast.SelectorExpr); ok {
									if sel.Sel.Name == "Group" {
										groups[id.Name] = groupFromCall(call, groups, svars, vars, src)
									}
									if g, ok := muxGroupFromCall(call, groups, svars, src); ok {
										groups[id.Name] = g
									}
									switch sel.Sel.Name {
									case "NewRouter":
										groups[id.Name] = groupCtx{kind: "mux"}
									case "New", "Default":
										base := exprString(sel.X)
										if base == "gin" || base == "echo" {
											groups[id.Name] = groupCtx{kind: base}
										}
									}
								}
							}
						}
					}
				case *ast.CallExpr:
					if sel, ok := x.Fun.(*ast.SelectorExpr); ok {
						if isHTTPMethod(sel.Sel.Name) {
							if r, ok := routeFromCall(x, rel, src, groups, vars); ok {
								emit(r)
							}
						}
						if sel.Sel.Name == "Register" || (sel.Sel.Name == "Register" && strings.Contains(exprString(sel.X), "huma")) {
							if r, ok := humaRoute(x, rel, src, vars); ok {
								emit(r)
							}
						}
						if !innerCalls[x] {
							for _, r := range muxRoutesFromCall(x, rel, src, groups, vars, svars) {
								emit(r)
							}
						}
					} else if id, ok := x.Fun.(*ast.Ident); ok && id.Name == "Register" {
						if r, ok := humaRoute(x, rel, src, vars); ok {
							emit(r)
						}
					}
					if sel, ok := x.Fun.(*ast.SelectorExpr); ok && sel.Sel.Name == "Use" {
						if id, ok := sel.X.(*ast.Ident); ok {
							g := groups[id.Name]
							g.mw = append(g.mw, x.Args...)
							g.source = sourceOf(x, src)
							groups[id.Name] = g
						}
					}
				}
				return true
			})
		}
	}
	// Helper functions receive a router group from their caller. Their routes were
	// collected relative to that group; instantiate them at each call site.
	for _, path := range files {
		src := srcs[path]
		f, err := parser.ParseFile(fset, path, src, 0)
		if err != nil {
			continue
		}
		rel, _ := filepath.Rel(*root, filepath.Dir(path))
		rel = filepath.ToSlash(rel)
		for _, decl := range f.Decls {
			fd, ok := decl.(*ast.FuncDecl)
			if !ok || fd.Body == nil {
				continue
			}
			groups := map[string]groupCtx{}
			svars := stringVars(fd)
			ast.Inspect(fd.Body, func(n ast.Node) bool {
				as, ok := n.(*ast.AssignStmt)
				if !ok || len(as.Lhs) != 1 || len(as.Rhs) != 1 {
					return true
				}
				id, ok := as.Lhs[0].(*ast.Ident)
				if !ok {
					return true
				}
				call, ok := as.Rhs[0].(*ast.CallExpr)
				if !ok {
					return true
				}
				if sel, ok := call.Fun.(*ast.SelectorExpr); ok {
					if sel.Sel.Name == "Group" {
						groups[id.Name] = groupFromCall(call, groups, svars, nil, src)
					}
					if g, ok := muxGroupFromCall(call, groups, svars, src); ok {
						groups[id.Name] = g
					}
				}
				return true
			})
			ast.Inspect(fd.Body, func(n ast.Node) bool {
				if call, ok := n.(*ast.CallExpr); ok {
					routes = append(routes, helperRoutesForCall(call, rel, src, helperTemplates, groups, svars)...)
				}
				return true
			})
		}
	}
	// dedupe by id+handler
	seen := map[string]bool{}
	var uniq []Route
	for _, r := range routes {
		k := r.ID + "|" + r.Handler
		if seen[k] {
			continue
		}
		seen[k] = true
		uniq = append(uniq, r)
	}
	sort.Slice(uniq, func(i, j int) bool {
		if uniq[i].ID != uniq[j].ID {
			return uniq[i].ID < uniq[j].ID
		}
		return uniq[i].Handler < uniq[j].Handler
	})
	f, err := os.Create(filepath.Join(*out, "routes.jsonl"))
	if err != nil {
		panic(err)
	}
	defer f.Close()
	enc := json.NewEncoder(f)
	for _, r := range uniq {
		if err := enc.Encode(r); err != nil {
			panic(err)
		}
	}
	fmt.Printf("routes=%d\n", len(uniq))
}

func typeName(e ast.Expr) string {
	switch t := e.(type) {
	case *ast.Ident:
		return t.Name
	case *ast.SelectorExpr:
		return t.Sel.Name
	case *ast.StarExpr:
		return typeName(t.X)
	case *ast.UnaryExpr:
		return typeName(t.X)
	}
	return ""
}

func normalizeMethod(s string) string {
	switch strings.ToUpper(strings.TrimSpace(s)) {
	case "HTTP.METHODGET", "GET":
		return "GET"
	case "HTTP.METHODPOST", "POST":
		return "POST"
	case "HTTP.METHODPUT", "PUT":
		return "PUT"
	case "HTTP.METHODPATCH", "PATCH":
		return "PATCH"
	case "HTTP.METHODDELETE", "DELETE":
		return "DELETE"
	case "HTTP.METHODHEAD", "HEAD":
		return "HEAD"
	case "HTTP.METHODOPTIONS", "OPTIONS":
		return "OPTIONS"
	}
	return strings.ToUpper(strings.TrimSpace(s))
}

func varTypes(fd *ast.FuncDecl) map[string]string {
	m := map[string]string{}
	if fd.Recv != nil && len(fd.Recv.List) > 0 && len(fd.Recv.List[0].Names) > 0 {
		m[fd.Recv.List[0].Names[0].Name] = typeName(fd.Recv.List[0].Type)
	}
	if fd.Type.Params != nil {
		for _, f := range fd.Type.Params.List {
			for _, n := range f.Names {
				m[n.Name] = typeName(f.Type)
			}
		}
	}
	ast.Inspect(fd.Body, func(n ast.Node) bool {
		as, ok := n.(*ast.AssignStmt)
		if !ok || len(as.Lhs) != 1 || len(as.Rhs) != 1 {
			return true
		}
		id, ok := as.Lhs[0].(*ast.Ident)
		if !ok {
			return true
		}
		if tn := typeName(as.Rhs[0]); tn != "" {
			m[id.Name] = tn
		}
		return true
	})
	return m
}

func resolveWithVars(e ast.Expr, pkg string, vars map[string]string) []string {
	if sel, ok := e.(*ast.SelectorExpr); ok {
		if id, ok := sel.X.(*ast.Ident); ok {
			if tn := vars[id.Name]; tn != "" {
				if _, ok := funcs[pkg+"."+tn+"."+sel.Sel.Name]; ok {
					return []string{pkg + "." + tn + "." + sel.Sel.Name}
				}
			}
		}
	}
	return resolve(e, pkg)
}
func resolve(e ast.Expr, pkg string) []string {
	var out []string
	seen := map[string]bool{}
	add := func(id string) {
		if !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	switch x := e.(type) {
	case *ast.Ident:
		for _, id := range byName[x.Name] {
			add(id)
		}
	case *ast.SelectorExpr:
		name := x.Sel.Name
		var preferred []string
		if id, ok := x.X.(*ast.Ident); ok {
			for _, fid := range byName[name] {
				if fn := funcs[fid]; fn != nil && filepath.Base(fn.Pkg) == id.Name {
					preferred = append(preferred, fid)
				}
			}
		}
		if len(preferred) > 0 {
			for _, id := range preferred {
				add(id)
			}
		} else {
			for _, id := range byName[name] {
				add(id)
			}
		}
	case *ast.CallExpr:
		for _, id := range resolve(x.Fun, pkg) {
			add(id)
		}
	case *ast.FuncLit: // inline; no id
	}
	// also collect names inside call chains
	ast.Inspect(e, func(n ast.Node) bool {
		if id, ok := n.(*ast.Ident); ok {
			for _, fid := range byName[id.Name] {
				add(fid)
			}
		}
		return true
	})
	return out
}
func isHTTPMethod(s string) bool {
	switch s {
	case "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "Any", "Handle":
		return true
	}
	return false
}
func exprString(e ast.Expr) string { var b strings.Builder; _ = formatNode(&b, e); return b.String() }
func formatNode(b *strings.Builder, e ast.Expr) error {
	switch x := e.(type) {
	case *ast.Ident:
		b.WriteString(x.Name)
	case *ast.SelectorExpr:
		formatNode(b, x.X)
		b.WriteString(".")
		b.WriteString(x.Sel.Name)
	case *ast.CallExpr:
		formatNode(b, x.Fun)
		b.WriteString("(...)")
	default:
		b.WriteString("expr")
	}
	return nil
}
func sourceOf(n ast.Node, src []byte) string {
	s := fset.Position(n.Pos()).Offset
	e := fset.Position(n.End()).Offset
	if s >= 0 && e <= len(src) {
		return string(src[s:e])
	}
	return ""
}
func stringArg(e ast.Expr) string {
	if bl, ok := e.(*ast.BasicLit); ok && bl.Kind == token.STRING {
		return strings.Trim(bl.Value, "\"`")
	}
	return ""
}
func groupFromCall(call *ast.CallExpr, groups map[string]groupCtx, svars map[string]string, vars map[string]string, src []byte) groupCtx {
	g := groupCtx{source: sourceOf(call, src)}
	parentPath, parentKind := "", ""
	if sel, ok := call.Fun.(*ast.SelectorExpr); ok {
		if id, ok := sel.X.(*ast.Ident); ok {
			if pg, ok := groups[id.Name]; ok {
				parentPath = pg.path
				parentKind = pg.kind
				g.mw = append(g.mw, pg.mw...)
			}
			if vars != nil {
				g.kind = kindFromType(vars[id.Name])
			}
		}
	}
	if parentKind != "" {
		g.kind = parentKind
	}
	if g.kind == "" {
		g.kind = "gin"
	}
	if len(call.Args) > 0 {
		g.path = joinRoute(parentPath, stringValue(call.Args[0], svars))
		if len(call.Args) > 1 {
			g.mw = append(g.mw, call.Args[1:]...)
		}
	}
	return g
}
func routeFromCall(call *ast.CallExpr, pkg string, src []byte, groups map[string]groupCtx, vars map[string]string) (Route, bool) {
	sel, ok := call.Fun.(*ast.SelectorExpr)
	if !ok || len(call.Args) < 2 {
		return Route{}, false
	}
	id, ok := sel.X.(*ast.Ident)
	if !ok {
		return Route{}, false
	}
	g, ok := groups[id.Name]
	if !ok {
		return Route{}, false
	}
	method := normalizeMethod(sel.Sel.Name)
	if method == "HANDLE" {
		method = "ANY"
	}
	path := stringArg(call.Args[0])
	if path == "" {
		return Route{}, false
	}
	handler := call.Args[len(call.Args)-1]
	var mw []ast.Expr
	if g.kind == "echo" {
		handler = call.Args[1]
		mw = append(mw, call.Args[2:]...)
	} else {
		mw = append(mw, call.Args[1:len(call.Args)-1]...)
	}
	gpath := g.path
	gsrc := g.source
	mw = append(mw, g.mw...)
	full := path
	if gpath != "" {
		full = strings.TrimRight(gpath, "/") + "/" + strings.TrimLeft(path, "/")
	}
	ids := resolveWithVars(handler, pkg, vars)
	hname := "inline"
	if len(ids) > 0 {
		hname = ids[0]
	}
	r := Route{ID: "route:" + method + " " + full, Method: method, Path: full, Handler: hname}
	parts := []string{fmt.Sprintf("Route: %s %s\nRegistration:\n%s", method, full, sourceOf(call, src))}
	if gsrc != "" {
		parts = append(parts, "Group context:\n"+gsrc)
	}
	if len(ids) > 0 {
		addFunc(&parts, &r.Members, ids[0], routeDepth)
	} else {
		parts = append(parts, "Handler:\n"+sourceOf(handler, src))
	}
	for _, m := range mw {
		parts = append(parts, "Middleware expression:\n"+sourceOf(m, src))
		for _, id := range resolveWithVars(m, pkg, vars) {
			addFunc(&parts, &r.Members, id, routeDepth)
		}
	}
	text := strings.Join(parts, "\n\n")
	if len(text) > 80000 {
		text = text[:80000]
		r.Truncated = true
	}
	r.Text = text
	r.Chars = len(text)
	return r, true
}
func humaRoute(call *ast.CallExpr, pkg string, src []byte, vars map[string]string) (Route, bool) {
	if len(call.Args) < 3 {
		return Route{}, false
	}
	var method, path string
	if cl, ok := call.Args[1].(*ast.CompositeLit); ok {
		for _, e := range cl.Elts {
			kv, ok := e.(*ast.KeyValueExpr)
			if !ok {
				continue
			}
			k, ok := kv.Key.(*ast.Ident)
			if !ok {
				continue
			}
			switch k.Name {
			case "Method":
				method = normalizeMethod(exprString(kv.Value))
			case "Path":
				path = stringArg(kv.Value)
			}
		}
	}
	if path == "" {
		return Route{}, false
	}
	handler := call.Args[len(call.Args)-1]
	ids := resolveWithVars(handler, pkg, vars)
	hname := "inline"
	if len(ids) > 0 {
		hname = ids[0]
	}
	r := Route{ID: "route:" + method + " " + path, Method: method, Path: path, Handler: hname}
	parts := []string{fmt.Sprintf("Route: %s %s\nRegistration:\n%s", method, path, sourceOf(call, src))}
	if len(ids) > 0 {
		addFunc(&parts, &r.Members, ids[0], routeDepth)
	} else {
		parts = append(parts, "Handler:\n"+sourceOf(handler, src))
	}
	text := strings.Join(parts, "\n\n")
	if len(text) > 80000 {
		text = text[:80000]
		r.Truncated = true
	}
	r.Text = text
	r.Chars = len(text)
	return r, true
}
func addFunc(parts *[]string, members *[]string, id string, depth int) {
	fn := funcs[id]
	if fn == nil {
		return
	}
	for _, m := range *members {
		if m == id {
			return
		}
	}
	*parts = append(*parts, "Function "+id+":\n"+fn.Source)
	*members = append(*members, id)
	if depth <= 0 {
		return
	}
	// callees same package first
	var cs []string
	for _, c := range fn.Calls {
		for _, cid := range byName[c] {
			cs = append(cs, cid)
		}
	}
	sort.SliceStable(cs, func(i, j int) bool {
		pi := strings.HasPrefix(cs[i], fn.Pkg+".")
		pj := strings.HasPrefix(cs[j], fn.Pkg+".")
		if pi != pj {
			return pi
		}
		return cs[i] < cs[j]
	})
	for _, cid := range cs {
		addFunc(parts, members, cid, depth-1)
	}
}
func fieldCalls(source, pkg string) []string {
	var out []string
	seen := map[string]bool{}
	for key, ids := range fieldMap {
		field := strings.TrimPrefix(key, strings.Split(key, ".")[0]+".")
		if strings.Contains(source, "."+field) {
			for _, id := range ids {
				if !seen[id] {
					seen[id] = true
					out = append(out, id)
				}
			}
		}
	}
	sort.Strings(out)
	return out
}
