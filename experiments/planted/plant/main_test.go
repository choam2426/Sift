package main

import (
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

const fixture = `package api

func Update(ctx *Context, repo *Repo) {
	if repo == nil || !ctx.Perm.CanWrite(repo) {
		ctx.Forbidden()
		return
	}
	// owners only
	if !ctx.IsOwner {
		ctx.NotFound()
		return
	}
	if err := os.MkdirAll(path, os.ModePerm); err != nil {
		return
	}
	items := store.Find(ctx, &store.FindOptions{
		OwnerID: ctx.Doer.ID,
	})
	_ = items
}

func Routes(m *Router) {
	m.Post("/new", reqToken(), reqRepoWriter(unitWiki), handler)
}
`

func ops(cs []Candidate) []string {
	var out []string
	for _, c := range cs {
		out = append(out, c.Op+" "+strings.TrimSpace(c.Removed))
	}
	sort.Strings(out)
	return out
}

func TestCandidates(t *testing.T) {
	got := ops(fileCandidates("api/api.go", []byte(fixture)))
	want := []string{
		"cond-weaken || !ctx.Perm.CanWrite(repo)",
		"guard-delete // owners only\n\tif !ctx.IsOwner {\n\t\tctx.NotFound()\n\t\treturn\n\t}",
		"guard-delete if repo == nil || !ctx.Perm.CanWrite(repo) {\n\t\tctx.Forbidden()\n\t\treturn\n\t}",
		"middleware-delete reqRepoWriter(unitWiki),",
		"middleware-delete reqToken(),",
		"scope-delete OwnerID: ctx.Doer.ID",
	}
	if strings.Join(got, "\n---\n") != strings.Join(want, "\n---\n") {
		t.Fatalf("candidates:\n%s\nwant:\n%s", strings.Join(got, "\n---\n"), strings.Join(want, "\n---\n"))
	}
}

const nested = `package api

func Sync(ctx *Context, required bool) error {
	if ctx.Rev != "" {
		// enforce override if enabled
		if required {
			if err := ctx.Enforce(ActionOverride); err != nil {
				return err
			}
		}
		log(ctx.Rev)
	}
	return nil
}
`

func TestApplyRemovesEmptiedParent(t *testing.T) {
	var id string
	for _, c := range fileCandidates("api/api.go", []byte(nested)) {
		if c.Op == "guard-delete" {
			id = c.ID
		}
	}
	dir := t.TempDir()
	path := filepath.Join(dir, "api", "api.go")
	_ = os.MkdirAll(filepath.Dir(path), 0o755)
	_ = os.WriteFile(path, []byte(nested), 0o644)
	if _, err := apply(dir, id); err != nil {
		t.Fatal(err)
	}
	out, _ := os.ReadFile(path)
	want := "\tif ctx.Rev != \"\" {\n\t\tlog(ctx.Rev)\n\t}\n"
	if !strings.Contains(string(out), want) || strings.Contains(string(out), "required {") || strings.Contains(string(out), "enforce override") {
		t.Fatalf("got:\n%s", out)
	}
}

func TestStripRemovesOrphanedHelpers(t *testing.T) {
	dir := t.TempDir()
	src := `package api

func TestOwner(t *testing.T) { ownerFixture(t) }

func TestOther(t *testing.T) { shared(t) }

func ownerFixture(t *testing.T) { deepHelper() }

func deepHelper() {}

func shared(t *testing.T) {}

func alreadyUnused() {}
`
	_ = os.WriteFile(filepath.Join(dir, "a_test.go"), []byte(src), 0o644)
	removed, err := strip(dir, []string{"TestOwner"})
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, r := range removed {
		got = append(got, r.Name)
	}
	sort.Strings(got)
	if strings.Join(got, ",") != "TestOwner,deepHelper,ownerFixture" {
		t.Fatalf("removed %v", got)
	}
	out, _ := os.ReadFile(filepath.Join(dir, "a_test.go"))
	if !strings.Contains(string(out), "func alreadyUnused()") || !strings.Contains(string(out), "func shared(") {
		t.Fatalf("kept code was removed:\n%s", out)
	}
}

func TestApplyKeepsValidGo(t *testing.T) {
	for _, c := range fileCandidates("api/api.go", []byte(fixture)) {
		dir := t.TempDir()
		path := filepath.Join(dir, "api", "api.go")
		_ = os.MkdirAll(filepath.Dir(path), 0o755)
		_ = os.WriteFile(path, []byte(fixture), 0o644)
		if _, err := apply(dir, c.ID); err != nil {
			t.Fatalf("%s: %v", c.ID, err)
		}
		out, _ := os.ReadFile(path)
		if strings.Contains(string(out), strings.TrimSpace(c.Removed)) {
			t.Errorf("%s: removed text still present", c.ID)
		}
		if c.Op == "scope-delete" && !strings.Contains(string(out), "&store.FindOptions{})") {
			t.Errorf("scope-delete left a dangling comma:\n%s", out)
		}
	}
}
