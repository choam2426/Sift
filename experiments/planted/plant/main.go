// Command plant lists and applies authorization-weakening mutations in Go source.
//
//	plant list  -root DIR            # JSONL candidates on stdout
//	plant apply -root DIR -id ID     # rewrite one file in place, JSON summary on stdout
//	plant strip -dir DIR -names A,B  # delete test funcs/methods by name from DIR/*_test.go
//	plant dropimport -file F -paths P,Q
//
// A candidate id is "<op>:<file>:<start>-<end>" with byte offsets into the
// original file, so it is stable for a fixed revision.
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

type Candidate struct {
	ID       string `json:"id"`
	Op       string `json:"op"`
	File     string `json:"file"`
	Package  string `json:"package"`
	Func     string `json:"func"`
	Line     int    `json:"line"`
	EndLine  int    `json:"end_line"`
	Start    int    `json:"start"`
	End      int    `json:"end"`
	Snippet  string `json:"snippet"`
	Removed  string `json:"removed"`
	FuncLine int    `json:"func_line"`
}

var (
	authzName = regexp.MustCompile(`(?i)(perm|authoriz|enforce|allowed|isallow|admin|owner|privilege|acl|rbac|collaborator|ismember|membership|restricted|issigned|isauthenticated|loggedin|signedin|superuser|userid|posterid|creatorid|authorid|doerid|accessmode|accesslevel|hasaccess|haveaccess|canaccess|checkaccess|accesscontrol|role|scope)|^[Cc]an(Read|Write|Access|Edit|Delete|View|Manage|Create|Admin|Modify|Update|Push|Merge|Approve|Comment|Upload|Download|Perform|Execute|See|Use|Do|Act|Change|Remove|Add|Set|Assign|Transfer|Fork|Enable|Close|Reopen|Lock|Unlock|Invite|Impersonate|Grant|Revoke)`)
	denyCall  = regexp.MustCompile(`(?i)(abort|forbidden|notfound|unauthori[sz]ed|error|deny|denied|reject|fail|redirect|status|errorf)`)
	errValue  = regexp.MustCompile(`(?i)(err|forbid|denied|unauthori|permission|notfound|invalid)`)
	mwName    = regexp.MustCompile(`^[Rr]eq[A-Z_]|(?i)(require|must|ensure|verify|auth|perm|admin|owner|acl|rbac|enforce|access|scope|signed|login|role)`)
	checkVerb = regexp.MustCompile(`(?i)^(evaluate|eval|check|verify|validate|has|is|can|ensure|require|must|authorize|enforce|allow|match)`)
	genFile   = regexp.MustCompile(`(_gen|_generated|\.pb|\.pb\.gw|_mock|_string)\.go$|(^|/)(zz_generated|generated)[^/]*\.go$`)
	routeFunc = regexp.MustCompile(`^(Get|Post|Put|Patch|Delete|Head|Options|Any|Group|Handle|HandleFunc|Combo|Route|Methods|Match|With|GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$`)
	optsType  = regexp.MustCompile(`(?i)(find|search|query|filter|list|lookup|cond|criteria|selector)`)
	scopeKey  = regexp.MustCompile(`(?i)^(owner|user|doer|actor|poster|creator|author|org|tenant|account|uid|subject|principal)(id|ids|name)?$|(owner|user|doer|actor|poster|creator|author|tenant|account)(id|ids)$`)
	identity  = regexp.MustCompile(`(?i)(doer|user|auth|session|claims|current|actor|principal|caller|signed|token|requester|viewer|identity|subject|ctx)`)
	skipDir   = regexp.MustCompile(`(^|/)(vendor|node_modules|testdata|test|tests|e2e|integration|mock|mocks|fake|fakes|testutil|testutils|internal/testing|cmd|migrations|contrib|docs|hack|scripts|tools|build)(/|$)`)
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: plant list|apply ...")
		os.Exit(2)
	}
	fs := flag.NewFlagSet(os.Args[1], flag.ExitOnError)
	root := fs.String("root", ".", "module root")
	id := fs.String("id", "", "candidate id (apply)")
	dir := fs.String("dir", "", "package directory (strip)")
	namesFlag := fs.String("names", "", "comma-separated func or method names (strip)")
	file := fs.String("file", "", "Go file (dropimport)")
	paths := fs.String("paths", "", "comma-separated import paths (dropimport)")
	_ = fs.Parse(os.Args[2:])
	switch os.Args[1] {
	case "strip":
		removed, err := strip(*dir, strings.Split(*namesFlag, ","))
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		_ = json.NewEncoder(os.Stdout).Encode(removed)
	case "dropimport":
		if err := dropImports(*file, strings.Split(*paths, ",")); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	case "list":
		enc := json.NewEncoder(os.Stdout)
		for _, c := range list(*root) {
			_ = enc.Encode(c)
		}
	case "apply":
		c, err := apply(*root, *id)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		_ = json.NewEncoder(os.Stdout).Encode(c)
	default:
		os.Exit(2)
	}
}

func list(root string) []Candidate {
	var out []Candidate
	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		rel, _ := filepath.Rel(root, path)
		rel = filepath.ToSlash(rel)
		if d.IsDir() {
			if rel != "." && (strings.HasPrefix(d.Name(), ".") || skipDir.MatchString(rel)) {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") || genFile.MatchString(rel) {
			return nil
		}
		src, err := os.ReadFile(path)
		if err != nil || isGenerated(src) {
			return nil
		}
		out = append(out, fileCandidates(rel, src)...)
		return nil
	})
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

func isGenerated(src []byte) bool {
	head := src
	if len(head) > 2048 {
		head = head[:2048]
	}
	return regexp.MustCompile(`(?m)^// Code generated .* DO NOT EDIT\.$`).Match(head)
}

func fileCandidates(rel string, src []byte) []Candidate {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, rel, src, parser.ParseComments)
	if err != nil {
		return nil
	}
	var out []Candidate
	off := func(p token.Pos) int { return fset.Position(p).Offset }
	line := func(p token.Pos) int { return fset.Position(p).Line }
	add := func(op string, fn *ast.FuncDecl, node ast.Node, start, end int) {
		c := Candidate{Op: op, File: rel, Package: filepath.ToSlash(filepath.Dir(rel)), Start: start, End: end,
			Line: line(node.Pos()), EndLine: line(node.End()),
			Snippet: string(src[off(node.Pos()):off(node.End())]), Removed: string(src[start:end])}
		if fn != nil {
			c.Func = funcName(fn)
			c.FuncLine = line(fn.Pos())
		}
		c.ID = fmt.Sprintf("%s:%s:%d-%d", op, rel, start, end)
		out = append(out, c)
	}
	for _, decl := range f.Decls {
		fn, _ := decl.(*ast.FuncDecl)
		var stack []ast.Node
		ast.Inspect(decl, func(n ast.Node) bool {
			if n == nil {
				stack = stack[:len(stack)-1]
				return true
			}
			var parent ast.Node
			if len(stack) > 0 {
				parent = stack[len(stack)-1]
			}
			stack = append(stack, n)
			switch x := n.(type) {
			case *ast.IfStmt:
				if x.Else != nil || !denies(x.Body) {
					return true
				}
				if p, ok := parent.(*ast.IfStmt); ok && p.Else == n {
					return true
				}
				if authzExpr(x.Init) || authzExpr(x.Cond) {
					if s, e, ok := lineRange(src, off(x.Pos()), off(x.End()), f, fset); ok {
						add("guard-delete", fn, x, s, e)
					}
				}
				if x.Init == nil {
					ops := flattenOr(x.Cond)
					if len(ops) >= 2 {
						for i, o := range ops {
							if !authzExpr(o) {
								continue
							}
							var s, e int
							if i == 0 {
								s, e = off(o.Pos()), off(ops[1].Pos())
							} else {
								s, e = off(ops[i-1].End()), off(o.End())
							}
							add("cond-weaken", fn, o, s, e)
						}
					}
				}
			case *ast.CallExpr:
				sel, ok := x.Fun.(*ast.SelectorExpr)
				if !ok {
					return true
				}
				if sel.Sel.Name == "Use" && len(x.Args) == 1 && mwExpr(x.Args[0]) {
					if es, ok := parent.(*ast.ExprStmt); ok {
						if s, e, ok := lineRange(src, off(es.Pos()), off(es.End()), f, fset); ok {
							add("middleware-delete", fn, es, s, e)
						}
					}
					return true
				}
				if !routeFunc.MatchString(sel.Sel.Name) || len(x.Args) < 2 {
					return true
				}
				if lit, ok := x.Args[0].(*ast.BasicLit); !ok || lit.Kind != token.STRING {
					return true // route registrations start with a path literal
				}
				for i, a := range x.Args {
					if i == 0 || !mwExpr(a) {
						continue
					}
					if _, isLit := a.(*ast.FuncLit); isLit {
						continue
					}
					if i == len(x.Args)-1 && !hasFuncLit(x.Args[:i]) {
						continue // last arg is the handler unless a group closure came earlier
					}
					var s, e int
					if i < len(x.Args)-1 {
						s, e = off(a.Pos()), off(x.Args[i+1].Pos())
					} else {
						s, e = off(x.Args[i-1].End()), off(a.End())
					}
					add("middleware-delete", fn, a, s, e)
				}
			case *ast.CompositeLit:
				if !optsType.MatchString(typeName(x.Type)) {
					return true
				}
				for i, el := range x.Elts {
					kv, ok := el.(*ast.KeyValueExpr)
					if !ok {
						continue
					}
					k, ok := kv.Key.(*ast.Ident)
					if !ok || !scopeKey.MatchString(k.Name) || !identExpr(kv.Value) {
						continue
					}
					var s, e int
					if i < len(x.Elts)-1 {
						s, e = off(kv.Pos()), off(x.Elts[i+1].Pos())
					} else if i > 0 {
						s, e = off(x.Elts[i-1].End()), off(kv.End())
					} else {
						s, e = off(kv.Pos()), off(kv.End())
					}
					add("scope-delete", fn, kv, s, e)
				}
			}
			return true
		})
	}
	return out
}

func funcName(fn *ast.FuncDecl) string {
	if fn.Recv != nil && len(fn.Recv.List) > 0 {
		return typeName(fn.Recv.List[0].Type) + "." + fn.Name.Name
	}
	return fn.Name.Name
}

func typeName(e ast.Expr) string {
	switch t := e.(type) {
	case *ast.Ident:
		return t.Name
	case *ast.StarExpr:
		return typeName(t.X)
	case *ast.SelectorExpr:
		return t.Sel.Name
	case *ast.IndexExpr:
		return typeName(t.X)
	case *ast.IndexListExpr:
		return typeName(t.X)
	}
	return ""
}

func names(n ast.Node) []string {
	var out []string
	if n == nil {
		return out
	}
	ast.Inspect(n, func(n ast.Node) bool {
		switch x := n.(type) {
		case *ast.Ident:
			out = append(out, x.Name)
		case *ast.SelectorExpr:
			out = append(out, x.Sel.Name)
		}
		return true
	})
	return out
}

// condNames collects the names a guard condition decides on: operands and
// called function names. Inside call arguments only nested call names count,
// and literals are skipped, so os.MkdirAll(p, os.ModePerm) is not authz.
func condNames(n ast.Node, inArgs bool, out *[]string) {
	switch x := n.(type) {
	case nil:
	case *ast.Ident:
		if !inArgs {
			*out = append(*out, x.Name)
		}
	case *ast.SelectorExpr:
		if !inArgs {
			*out = append(*out, x.Sel.Name)
			condNames(x.X, false, out)
		}
	case *ast.CallExpr:
		*out = append(*out, names(x.Fun)...)
		if inArgs || checkVerb.MatchString(callName(x)) {
			for _, a := range x.Args {
				condNames(a, true, out)
			}
		}
	case *ast.CompositeLit, *ast.FuncLit, *ast.BasicLit:
	case *ast.UnaryExpr:
		condNames(x.X, inArgs, out)
	case *ast.BinaryExpr:
		condNames(x.X, inArgs, out)
		condNames(x.Y, inArgs, out)
	case *ast.ParenExpr:
		condNames(x.X, inArgs, out)
	case *ast.StarExpr:
		condNames(x.X, inArgs, out)
	case *ast.IndexExpr:
		condNames(x.X, inArgs, out)
	case *ast.TypeAssertExpr:
		condNames(x.X, inArgs, out)
	case *ast.AssignStmt:
		for _, r := range x.Rhs {
			condNames(r, inArgs, out)
		}
	case *ast.ExprStmt:
		condNames(x.X, inArgs, out)
	}
}

func authzExpr(n ast.Node) bool {
	if n == nil || isNil(n) {
		return false
	}
	var ns []string
	condNames(n, false, &ns)
	for _, s := range ns {
		if authzName.MatchString(s) {
			return true
		}
	}
	return false
}

func isNil(n ast.Node) bool {
	switch x := n.(type) {
	case ast.Stmt:
		return x == nil
	case ast.Expr:
		return x == nil
	}
	return false
}

func identExpr(e ast.Expr) bool {
	for _, s := range names(e) {
		if identity.MatchString(s) {
			return true
		}
	}
	return false
}

func mwExpr(e ast.Expr) bool {
	switch x := e.(type) {
	case *ast.Ident:
		return mwName.MatchString(x.Name)
	case *ast.SelectorExpr:
		return mwName.MatchString(x.Sel.Name)
	case *ast.CallExpr:
		return mwExpr(x.Fun)
	}
	return false
}

func hasFuncLit(args []ast.Expr) bool {
	for _, a := range args {
		if _, ok := a.(*ast.FuncLit); ok {
			return true
		}
	}
	return false
}

func flattenOr(e ast.Expr) []ast.Expr {
	if b, ok := e.(*ast.BinaryExpr); ok && b.Op == token.LOR {
		return append(flattenOr(b.X), b.Y)
	}
	return []ast.Expr{e}
}

// denies reports whether a guard body rejects the request: it returns an
// error or false, returns right after a rejecting call, or ends with one.
func denies(b *ast.BlockStmt) bool {
	if b == nil || len(b.List) == 0 {
		return false
	}
	for i, s := range b.List {
		r, ok := s.(*ast.ReturnStmt)
		if !ok {
			continue
		}
		if len(r.Results) == 0 {
			return i > 0 && denyStmt(b.List[i-1])
		}
		for _, v := range r.Results {
			if denyValue(v) {
				return true
			}
		}
		return false
	}
	return denyStmt(b.List[len(b.List)-1])
}

func callName(e ast.Expr) string {
	call, ok := e.(*ast.CallExpr)
	if !ok {
		return ""
	}
	switch f := call.Fun.(type) {
	case *ast.Ident:
		return f.Name
	case *ast.SelectorExpr:
		return f.Sel.Name
	}
	return ""
}

func denyStmt(s ast.Stmt) bool {
	es, ok := s.(*ast.ExprStmt)
	if !ok {
		return false
	}
	name := callName(es.X)
	return name == "panic" || name != "" && denyCall.MatchString(name)
}

func denyValue(v ast.Expr) bool {
	switch x := v.(type) {
	case *ast.Ident:
		return x.Name == "false" || errValue.MatchString(x.Name)
	case *ast.SelectorExpr:
		return errValue.MatchString(x.Sel.Name)
	case *ast.CallExpr:
		return denyCall.MatchString(callName(x)) || regexp.MustCompile(`^(New|Wrap|Wrapf|Errorf|WithStack)$`).MatchString(callName(x)) || errValue.MatchString(callName(x))
	case *ast.CompositeLit:
		return errValue.MatchString(typeName(x.Type))
	case *ast.UnaryExpr:
		return denyValue(x.X)
	}
	return false
}

// lineRange widens [s,e) to whole lines and includes comment lines attached
// directly above. It fails if the statement shares a line with other code.
func lineRange(src []byte, s, e int, f *ast.File, fset *token.FileSet) (int, int, bool) {
	ls := bytes.LastIndexByte(src[:s], '\n') + 1
	if strings.TrimSpace(string(src[ls:s])) != "" {
		return 0, 0, false
	}
	le := e
	if i := bytes.IndexByte(src[e:], '\n'); i >= 0 {
		le = e + i + 1
	} else {
		le = len(src)
	}
	rest := strings.TrimSpace(string(src[e:le]))
	if rest != "" && !strings.HasPrefix(rest, "//") {
		return 0, 0, false
	}
	for ls > 0 {
		prev := bytes.LastIndexByte(src[:ls-1], '\n') + 1
		t := strings.TrimSpace(string(src[prev : ls-1]))
		if !strings.HasPrefix(t, "//") {
			break
		}
		ls = prev
	}
	return ls, le, true
}

func apply(root, id string) (Candidate, error) {
	parts := strings.SplitN(id, ":", 3)
	if len(parts) != 3 {
		return Candidate{}, fmt.Errorf("bad id %q", id)
	}
	rel := parts[1]
	r := strings.SplitN(parts[2], "-", 2)
	s, err1 := strconv.Atoi(r[0])
	e, err2 := strconv.Atoi(r[1])
	if err1 != nil || err2 != nil {
		return Candidate{}, fmt.Errorf("bad range %q", parts[2])
	}
	path := filepath.Join(root, filepath.FromSlash(rel))
	src, err := os.ReadFile(path)
	if err != nil {
		return Candidate{}, err
	}
	var found *Candidate
	for _, c := range fileCandidates(rel, src) {
		if c.ID == id {
			c := c
			found = &c
		}
	}
	if found == nil {
		return Candidate{}, fmt.Errorf("candidate %s not found (source changed?)", id)
	}
	if parts[0] == "guard-delete" {
		s, e = widenEmptyParent(rel, src, s, e)
	}
	if parts[0] == "scope-delete" {
		// a lone keyed element keeps its trailing comma in the id range; drop it
		before := strings.TrimRight(string(src[:s]), " \t\n")
		after := strings.TrimLeft(string(src[e:]), " \t\n")
		if strings.HasSuffix(before, "{") && strings.HasPrefix(after, ",") {
			e = len(src) - len(after) + 1
		}
	}
	out := append(append([]byte{}, src[:s]...), src[e:]...)
	if parts[0] == "guard-delete" || parts[0] == "middleware-delete" && strings.HasSuffix(string(src[s:e]), "\n") {
		out = tidyBlankLines(out, s)
	}
	if formatted, err := format.Source(src); err == nil && bytes.Equal(formatted, src) {
		if f2, err := format.Source(out); err == nil {
			out = f2
		} else {
			return Candidate{}, fmt.Errorf("mutant does not parse: %v", err)
		}
	}
	if err := os.WriteFile(path, out, 0o644); err != nil {
		return Candidate{}, err
	}
	return *found, nil
}

// widenEmptyParent extends a guard deletion to an enclosing `if` whose body
// would become empty, so the mutant does not show an empty block. The parent
// must have no init, no else, and a call-free condition.
func widenEmptyParent(rel string, src []byte, s, e int) (int, int) {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, rel, src, parser.ParseComments)
	if err != nil {
		return s, e
	}
	off := func(p token.Pos) int { return fset.Position(p).Offset }
	for {
		widened := false
		ast.Inspect(f, func(n ast.Node) bool {
			if widened {
				return false
			}
			x, ok := n.(*ast.IfStmt)
			if !ok || x.Init != nil || x.Else != nil || len(x.Body.List) != 1 {
				return true
			}
			inner := x.Body.List[0]
			if off(inner.Pos()) < s || off(inner.End()) > e || hasCall(x.Cond) {
				return true
			}
			if ls, le, ok := lineRange(src, off(x.Pos()), off(x.End()), f, fset); ok && (ls < s || le > e) {
				s, e, widened = ls, le, true
			}
			return !widened
		})
		if !widened {
			return s, e
		}
	}
}

func hasCall(e ast.Expr) bool {
	found := false
	ast.Inspect(e, func(n ast.Node) bool {
		if _, ok := n.(*ast.CallExpr); ok {
			found = true
		}
		return !found
	})
	return found
}

type Removed struct {
	File string `json:"file"`
	Name string `json:"name"`
	Recv string `json:"recv,omitempty"`
}

// identCounts counts identifier occurrences by name in all Go files of dir.
func identCounts(dir string) map[string]int {
	counts := map[string]int{}
	files, _ := filepath.Glob(filepath.Join(dir, "*.go"))
	for _, path := range files {
		f, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			continue
		}
		ast.Inspect(f, func(n ast.Node) bool {
			if id, ok := n.(*ast.Ident); ok {
				counts[id.Name]++
			}
			return true
		})
	}
	return counts
}

// strip deletes test functions or suite methods with the given names, with
// their doc comments, from the *_test.go files of one directory. Unexported
// test helpers that only the deleted code used are deleted too: an unused
// helper about the removed behavior would point at the mutation.
func strip(dir string, names []string) ([]Removed, error) {
	before := identCounts(dir)
	removed, err := stripOnce(dir, names)
	if err != nil {
		return nil, err
	}
	for {
		after := identCounts(dir)
		var dead []string
		files, _ := filepath.Glob(filepath.Join(dir, "*_test.go"))
		for _, path := range files {
			f, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
			if err != nil {
				continue
			}
			for _, d := range f.Decls {
				fd, ok := d.(*ast.FuncDecl)
				if !ok || fd.Name.IsExported() || fd.Name.Name == "init" {
					continue
				}
				if after[fd.Name.Name] == 1 && before[fd.Name.Name] > 1 {
					dead = append(dead, fd.Name.Name)
				}
			}
		}
		if len(dead) == 0 {
			return removed, nil
		}
		more, err := stripOnce(dir, dead)
		if err != nil {
			return nil, err
		}
		removed = append(removed, more...)
	}
}

func stripOnce(dir string, names []string) ([]Removed, error) {
	want := map[string]bool{}
	for _, n := range names {
		if n = strings.TrimSpace(n); n != "" {
			want[n] = true
		}
	}
	files, _ := filepath.Glob(filepath.Join(dir, "*_test.go"))
	sort.Strings(files)
	removed := []Removed{}
	for _, path := range files {
		src, err := os.ReadFile(path)
		if err != nil {
			return nil, err
		}
		fset := token.NewFileSet()
		f, err := parser.ParseFile(fset, path, src, parser.ParseComments)
		if err != nil {
			return nil, err
		}
		type span struct{ s, e int }
		var spans []span
		for _, d := range f.Decls {
			fd, ok := d.(*ast.FuncDecl)
			if !ok || !want[fd.Name.Name] {
				continue
			}
			start := fd.Pos()
			if fd.Doc != nil {
				start = fd.Doc.Pos()
			}
			s := fset.Position(start).Offset
			e := fset.Position(fd.End()).Offset
			s = bytes.LastIndexByte(src[:s], '\n') + 1
			if i := bytes.IndexByte(src[e:], '\n'); i >= 0 {
				e += i + 1
			} else {
				e = len(src)
			}
			spans = append(spans, span{s, e})
			r := Removed{File: filepath.Base(path), Name: fd.Name.Name}
			if fd.Recv != nil && len(fd.Recv.List) > 0 {
				r.Recv = typeName(fd.Recv.List[0].Type)
			}
			removed = append(removed, r)
		}
		if len(spans) == 0 {
			continue
		}
		out := []byte{}
		prev := 0
		for _, sp := range spans {
			out = append(out, src[prev:sp.s]...)
			prev = sp.e
		}
		out = append(out, src[prev:]...)
		if f2, err := format.Source(out); err == nil {
			out = f2
		}
		if err := os.WriteFile(path, out, 0o644); err != nil {
			return nil, err
		}
	}
	return removed, nil
}

// dropImports removes import specs by path; used after strip when the
// compiler reports "imported and not used".
func dropImports(path string, paths []string) error {
	src, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	drop := map[string]bool{}
	for _, p := range paths {
		drop[strings.TrimSpace(p)] = true
	}
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, path, src, parser.ParseComments)
	if err != nil {
		return err
	}
	type span struct{ s, e int }
	var spans []span
	for _, imp := range f.Imports {
		p, _ := strconv.Unquote(imp.Path.Value)
		if !drop[p] {
			continue
		}
		s := fset.Position(imp.Pos()).Offset
		e := fset.Position(imp.End()).Offset
		ls := bytes.LastIndexByte(src[:s], '\n') + 1
		le := e
		if i := bytes.IndexByte(src[e:], '\n'); i >= 0 {
			le = e + i + 1
		}
		if strings.TrimSpace(string(src[ls:s])) == "" && strings.TrimSpace(string(src[e:le])) == "" {
			s, e = ls, le
		} else if strings.HasPrefix(strings.TrimSpace(string(src[ls:s])), "import") {
			s, e = ls, le // single-line `import "x"`
		}
		spans = append(spans, span{s, e})
	}
	sort.Slice(spans, func(i, j int) bool { return spans[i].s < spans[j].s })
	out := []byte{}
	prev := 0
	for _, sp := range spans {
		out = append(out, src[prev:sp.s]...)
		prev = sp.e
	}
	out = append(out, src[prev:]...)
	if f2, err := format.Source(out); err == nil {
		out = f2
	}
	return os.WriteFile(path, out, 0o644)
}

// tidyBlankLines removes a blank line left at the splice point when it would
// sit next to another blank line or a block brace.
func tidyBlankLines(b []byte, at int) []byte {
	lines := strings.Split(string(b), "\n")
	pos, idx := 0, 0
	for i, l := range lines {
		if pos+len(l) >= at {
			idx = i
			break
		}
		pos += len(l) + 1
	}
	blank := func(i int) bool { return i >= 0 && i < len(lines) && strings.TrimSpace(lines[i]) == "" }
	prevOpen := idx > 0 && strings.HasSuffix(strings.TrimSpace(lines[idx-1]), "{")
	nextClose := idx < len(lines) && strings.HasPrefix(strings.TrimSpace(lines[idx]), "}")
	switch {
	case blank(idx-1) && blank(idx):
		lines = append(lines[:idx], lines[idx+1:]...)
	case prevOpen && blank(idx):
		lines = append(lines[:idx], lines[idx+1:]...)
	case nextClose && blank(idx-1):
		lines = append(lines[:idx-1], lines[idx:]...)
	}
	return []byte(strings.Join(lines, "\n"))
}
