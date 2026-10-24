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

type Function struct {
	ID       string   `json:"id"`
	Package  string   `json:"package"`
	Receiver string   `json:"receiver,omitempty"`
	Name     string   `json:"name"`
	File     string   `json:"file"`
	Line     int      `json:"line"`
	Chars    int      `json:"chars"`
	Source   string   `json:"source"`
	Calls    []string `json:"calls"`
}

type Unit struct {
	ID        string   `json:"id"`
	Target    string   `json:"target"`
	Package   string   `json:"package"`
	File      string   `json:"file,omitempty"`
	Line      int      `json:"line,omitempty"`
	Members   []string `json:"members"`
	Chars     int      `json:"chars"`
	Text      string   `json:"text"`
	Truncated bool     `json:"truncated"`
}

func main() {
	root := flag.String("root", ".", "project root")
	pkgs := flag.String("packages", "", "comma-separated package directories relative to root")
	out := flag.String("out", ".", "output directory")
	flag.Parse()
	allPackages := strings.TrimSpace(*pkgs) == ""
	scope := map[string]bool{}
	for _, p := range strings.Split(*pkgs, ",") {
		p = strings.TrimSpace(strings.TrimPrefix(p, "./"))
		if p != "" {
			scope[p] = true
		}
	}
	fset := token.NewFileSet()
	funcs := map[string]*Function{}
	types := map[string]map[string]string{} // package -> type name -> source
	var order []string
	_ = filepath.WalkDir(*root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			base := d.Name()
			if base == ".git" || base == "vendor" || base == "node_modules" || base == "frontend" || base == "dist" || base == "testdata" {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		rel, _ := filepath.Rel(*root, filepath.Dir(path))
		rel = filepath.ToSlash(rel)
		if !allPackages && !scope[rel] {
			return nil
		}
		src, err := os.ReadFile(path)
		if err != nil {
			return nil
		}
		f, err := parser.ParseFile(fset, path, src, parser.ParseComments)
		if err != nil {
			return nil
		}
		pkg := rel
		if types[pkg] == nil {
			types[pkg] = map[string]string{}
		}
		for _, decl := range f.Decls {
			if gd, ok := decl.(*ast.GenDecl); ok && gd.Tok == token.TYPE {
				for _, spec := range gd.Specs {
					if ts, ok := spec.(*ast.TypeSpec); ok {
						start := fset.Position(ts.Pos()).Offset
						end := fset.Position(ts.End()).Offset
						if start >= 0 && end <= len(src) {
							types[pkg][ts.Name.Name] = string(src[start:end])
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
				if star, ok := t.(*ast.StarExpr); ok {
					t = star.X
				}
				if id, ok := t.(*ast.Ident); ok {
					recv = id.Name
				}
			}
			id := pkg + "." + fd.Name.Name
			if recv != "" {
				id = pkg + "." + recv + "." + fd.Name.Name
			}
			start := fset.Position(fd.Pos()).Offset
			end := fset.Position(fd.End()).Offset
			if start < 0 || end > len(src) {
				continue
			}
			code := string(src[start:end])
			calls := map[string]bool{}
			ast.Inspect(fd.Body, func(n ast.Node) bool {
				call, ok := n.(*ast.CallExpr)
				if !ok {
					return true
				}
				switch fun := call.Fun.(type) {
				case *ast.Ident:
					calls[fun.Name] = true
				case *ast.SelectorExpr:
					calls[fun.Sel.Name] = true
				}
				return true
			})
			cs := make([]string, 0, len(calls))
			for c := range calls {
				cs = append(cs, c)
			}
			sort.Strings(cs)
			fn := &Function{ID: id, Package: pkg, Receiver: recv, Name: fd.Name.Name,
				File: filepath.ToSlash(path), Line: fset.Position(fd.Pos()).Line,
				Chars: len(code), Source: code, Calls: cs}
			funcs[id] = fn
			order = append(order, id)
		}
		return nil
	})
	sort.Strings(order)
	// callers by simple name
	callers := map[string][]string{}
	for _, id := range order {
		for _, c := range funcs[id].Calls {
			callers[c] = append(callers[c], id)
		}
	}
	byName := map[string][]string{}
	for _, id := range order {
		byName[funcs[id].Name] = append(byName[funcs[id].Name], id)
	}
	var funits, bunits []Unit
	for _, id := range order {
		fn := funcs[id]
		funits = append(funits, Unit{ID: id, Target: id, Package: fn.Package, File: fn.File, Line: fn.Line, Members: []string{id}, Chars: len(fn.Source), Text: fn.Source})
		seen := map[string]bool{id: true}
		members := []string{id}
		parts := []string{fmt.Sprintf("Target: %s\n%s", id, fn.Source)}
		if fn.Receiver != "" {
			if decl, ok := types[fn.Package][fn.Receiver]; ok {
				parts = append(parts, fmt.Sprintf("Receiver type %s:\n%s", fn.Receiver, decl))
			}
		}
		add := func(cid string) {
			if seen[cid] {
				return
			}
			snippet := fmt.Sprintf("Related %s:\n%s", cid, funcs[cid].Source)
			if len(strings.Join(parts, "\n\n"))+len(snippet) > 80000 {
				return
			}
			seen[cid] = true
			members = append(members, cid)
			parts = append(parts, snippet)
		}
		// callees first, same package preferred
		var callees []string
		for _, c := range fn.Calls {
			callees = append(callees, byName[c]...)
		}
		sort.SliceStable(callees, func(i, j int) bool {
			pi := strings.HasPrefix(callees[i], fn.Package+".")
			pj := strings.HasPrefix(callees[j], fn.Package+".")
			if pi != pj {
				return pi
			}
			return callees[i] < callees[j]
		})
		for _, cid := range callees {
			add(cid)
		}
		var cls []string
		for _, c := range fn.Calls {
			cls = append(cls, callers[c]...)
		}
		sort.SliceStable(cls, func(i, j int) bool {
			pi := strings.HasPrefix(cls[i], fn.Package+".")
			pj := strings.HasPrefix(cls[j], fn.Package+".")
			if pi != pj {
				return pi
			}
			return cls[i] < cls[j]
		})
		for _, cid := range cls {
			add(cid)
		}
		text := strings.Join(parts, "\n\n")
		truncated := false
		if len(text) > 80000 {
			text = text[:80000]
			truncated = true
		}
		bunits = append(bunits, Unit{ID: id, Target: id, Package: fn.Package, Members: members, Chars: len(text), Text: text, Truncated: truncated})
	}
	writeFunctions(filepath.Join(*out, "functions.jsonl"), funits)
	writeUnits(filepath.Join(*out, "units.jsonl"), bunits)
	fmt.Printf("functions=%d units=%d\n", len(funits), len(bunits))
}

func writeFunctions(path string, rows []Unit) {
	f, err := os.Create(path)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	enc := json.NewEncoder(f)
	for _, r := range rows {
		row := map[string]any{"id": r.ID, "package": r.Package, "chars": r.Chars, "text": r.Text, "file": r.File, "line": r.Line}
		if err := enc.Encode(row); err != nil {
			panic(err)
		}
	}
}

func writeUnits(path string, rows []Unit) {
	f, err := os.Create(path)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	enc := json.NewEncoder(f)
	for _, r := range rows {
		if err := enc.Encode(r); err != nil {
			panic(err)
		}
	}
}
