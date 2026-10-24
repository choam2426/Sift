package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"golang.org/x/tools/go/callgraph/cha"
	"golang.org/x/tools/go/packages"
	"golang.org/x/tools/go/ssa"
	"golang.org/x/tools/go/ssa/ssautil"
)

type Route struct {
	ID        string   `json:"ID"`
	Method    string   `json:"Method"`
	Path      string   `json:"Path"`
	Handler   string   `json:"Handler"`
	Members   []string `json:"Members"`
	Chars     int      `json:"Chars"`
	Text      string   `json:"Text"`
	Truncated bool     `json:"Truncated"`
}

var keyPrefix = ""

type node struct {
	fn      *ssa.Function
	key     string
	depth   int
	project bool
}

func modulePath(root string) string {
	f, err := os.Open(filepath.Join(root, "go.mod"))
	if err != nil {
		return ""
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if strings.HasPrefix(line, "module ") {
			return strings.TrimSpace(strings.TrimPrefix(line, "module "))
		}
	}
	return ""
}

func funcKey(module, pkgPath string, fn *ssa.Function) string {
	rel := strings.TrimPrefix(pkgPath, module)
	rel = strings.TrimPrefix(rel, "/")
	if rel == "" {
		rel = "."
	}
	name := fn.Name()
	if recv := fn.Signature.Recv(); recv != nil {
		t := recv.Type().String()
		t = strings.TrimPrefix(t, "*")
		if i := strings.LastIndex(t, "."); i >= 0 {
			t = t[i+1:]
		}
		return rel + "." + t + "." + name
	}
	return rel + "." + name
}

func sourceFor(fset *token.FileSet, fn *ssa.Function, files map[string][]byte) string {
	node := fn.Syntax()
	if node == nil {
		return ""
	}
	p := fset.Position(node.Pos())
	e := fset.Position(node.End())
	if p.Filename == "" || e.Filename != p.Filename || p.Offset < 0 || e.Offset < p.Offset {
		return ""
	}
	src := files[p.Filename]
	if src == nil {
		b, err := os.ReadFile(p.Filename)
		if err != nil {
			return ""
		}
		files[p.Filename] = b
		src = b
	}
	if e.Offset > len(src) {
		return ""
	}
	return string(src[p.Offset:e.Offset])
}

func main() {
	root := flag.String("root", ".", "module root")
	routesPath := flag.String("routes", "", "input routes.jsonl")
	pkgPatterns := flag.String("pkgs", "", "comma-separated package patterns; default derives from handlers")
	out := flag.String("out", "", "output routes.jsonl")
	maxDepth := flag.Int("max-depth", 4, "maximum call-graph depth")
	maxSources := flag.Int("max-sources", 8, "maximum call-graph function sources")
	maxIndex := flag.Int("max-index", 400, "maximum call-graph index entries in route text")
	prefix := flag.String("key-prefix", "", "prefix added to call-graph keys for nested modules")
	flag.Parse()
	keyPrefix = *prefix
	if *routesPath == "" || *out == "" {
		panic("-routes and -out required")
	}

	var routes []Route
	f, err := os.Open(*routesPath)
	if err != nil {
		panic(err)
	}
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1024*1024), 16*1024*1024)
	for sc.Scan() {
		var r Route
		if err := json.Unmarshal(sc.Bytes(), &r); err != nil {
			panic(err)
		}
		routes = append(routes, r)
	}
	f.Close()

	patterns := []string{}
	if *pkgPatterns != "" {
		for _, p := range strings.Split(*pkgPatterns, ",") {
			if p = strings.TrimSpace(p); p != "" {
				patterns = append(patterns, p)
			}
		}
	} else {
		seen := map[string]bool{}
		for _, r := range routes {
			h := r.Handler
			if h == "" || h == "inline" {
				continue
			}
			dir := strings.SplitN(h, ".", 2)[0]
			if dir == "" || seen[dir] {
				continue
			}
			seen[dir] = true
			if strings.HasPrefix(dir, "/") {
				patterns = append(patterns, dir)
			} else {
				patterns = append(patterns, "./"+dir)
			}
		}
	}
	if len(patterns) == 0 {
		patterns = []string{"./..."}
	}
	cfg := &packages.Config{Mode: packages.LoadAllSyntax, Dir: *root}
	pkgs, err := packages.Load(cfg, patterns...)
	if err != nil {
		panic(err)
	}
	if n := packages.PrintErrors(pkgs); n > 0 {
		fmt.Fprintf(os.Stderr, "warning: %d package load errors\n", n)
	}
	all := []*packages.Package{}
	seenPkg := map[string]bool{}
	var visit func(*packages.Package)
	visit = func(p *packages.Package) {
		if p == nil || seenPkg[p.ID] {
			return
		}
		seenPkg[p.ID] = true
		for _, imp := range p.Imports {
			visit(imp)
		}
		all = append(all, p)
	}
	for _, p := range pkgs {
		visit(p)
	}
	prog, _ := ssautil.AllPackages(all, ssa.InstantiateGenerics)
	prog.Build()
	cg := cha.CallGraph(prog)
	module := modulePath(*root)

	byKey := map[string]*ssa.Function{}
	for fn := range cg.Nodes {
		if fn == nil || fn.Pkg == nil || fn.Synthetic != "" || fn.Blocks == nil {
			continue
		}
		if recv := fn.Signature.Recv(); recv != nil {
			byKey[funcKey(module, fn.Pkg.Pkg.Path(), fn)] = fn
		} else {
			byKey[funcKey(module, fn.Pkg.Pkg.Path(), fn)] = fn
		}
	}
	files := map[string][]byte{}
	fset := prog.Fset

	for i := range routes {
		r := &routes[i]
		start := byKey[r.Handler]
		if start == nil {
			continue
		}
		seen := map[string]bool{}
		for _, m := range r.Members {
			seen[m] = true
		}
		var order []node
		queue := []node{{fn: start, key: r.Handler, depth: 0}}
		for len(queue) > 0 && len(order) < 2000 {
			n := queue[0]
			queue = queue[1:]
			if n.fn == nil || n.depth > *maxDepth {
				continue
			}
			if seen[n.key] && n.depth > 0 {
				continue
			}
			seen[n.key] = true
			order = append(order, n)
			nodeCg := cg.Nodes[n.fn]
			if nodeCg == nil {
				continue
			}
			for _, edge := range nodeCg.Out {
				callee := edge.Callee
				if callee == nil || callee.Func == nil || callee.Func.Pkg == nil || callee.Func.Synthetic != "" {
					continue
				}
				key := funcKey(module, callee.Func.Pkg.Pkg.Path(), callee.Func)
				if !seen[key] {
					project := module != "" && strings.HasPrefix(callee.Func.Pkg.Pkg.Path(), module)
					queue = append(queue, node{fn: callee.Func, key: key, depth: n.depth + 1, project: project})
				}
			}
		}
		sort.SliceStable(order, func(i, j int) bool {
			if order[i].depth != order[j].depth {
				return order[i].depth < order[j].depth
			}
			if order[i].project != order[j].project {
				return order[i].project
			}
			return order[i].key < order[j].key
		})
		var index strings.Builder
		var sources strings.Builder
		srcCount := 0
		indexCount := 0
		for _, n := range order {
			if n.key == r.Handler {
				continue
			}
			if indexCount < *maxIndex {
				index.WriteString(fmt.Sprintf("- %s (depth %d)\n", n.key, n.depth))
				indexCount++
			}
			if srcCount < *maxSources {
				if src := sourceFor(fset, n.fn, files); src != "" {
					sources.WriteString(fmt.Sprintf("Function %s (depth %d):\n%s\n\n", n.key, n.depth, src))
					srcCount++
				}
			}
			if !contains(r.Members, n.key) {
				r.Members = append(r.Members, n.key)
			}
		}
		if index.Len() > 0 {
			add := "\n\nCall graph (depth " + fmt.Sprint(*maxDepth) + "):\n" + index.String()
			if sources.Len() > 0 {
				add += "\nSelected call-graph sources:\n" + sources.String()
			}
			if len(r.Text)+len(add) > 80000 {
				// Keep the complete index (small, decision-relevant) and truncate only sources.
				head := "\n\nCall graph (depth " + fmt.Sprint(*maxDepth) + "):\n" + index.String()
				room := 80000 - len(r.Text) - len(head)
				if room > 0 {
					head += "\nSelected call-graph sources:\n" + sources.String()[:min(room, sources.Len())]
				}
				add = head
				r.Truncated = true
			}
			r.Text += add
			if len(r.Text) > 80000 {
				r.Text = r.Text[:80000]
				r.Truncated = true
			}
		}
		r.Chars = len(r.Text)
	}

	if dir := filepath.Dir(*out); dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			panic(err)
		}
	}
	outf, err := os.Create(*out)
	if err != nil {
		panic(err)
	}
	defer outf.Close()
	enc := json.NewEncoder(outf)
	for _, r := range routes {
		if err := enc.Encode(r); err != nil {
			panic(err)
		}
	}
	fmt.Printf("enriched=%d module=%s\n", len(routes), module)
}

func contains(xs []string, x string) bool {
	for _, s := range xs {
		if s == x {
			return true
		}
	}
	return false
}
func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
