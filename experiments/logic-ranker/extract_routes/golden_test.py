#!/usr/bin/env python3
"""Golden extraction tests. Run from this directory: python3 golden_test.py."""
import json
import pathlib
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def run_fixture(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / 'src'
        out = pathlib.Path(tmp) / 'out'
        root.mkdir()
        out.mkdir()
        for name, text in files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        proc = subprocess.run(
            ['go', 'run', '.', '-root', str(root), '-out', str(out)],
            cwd=HERE, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise AssertionError(proc.stderr)
        rows = [json.loads(line) for line in (out / 'routes.jsonl').read_text().splitlines()]
        return rows


def ids(rows):
    return {r['ID'] for r in rows}


def text_for(rows, route_id):
    for r in rows:
        if r['ID'] == route_id:
            return r['Text']
    raise AssertionError(f'missing {route_id}')


def main():
    gin_rows = run_fixture({
        'routes.go': '''package fixtures
import "github.com/gin-gonic/gin"
func routes() {
 r := gin.New()
 api := r.Group("/api", Auth)
 api.Use(First, Second)
 api.GET("/users/:id", GetUser)
}
func GetUser() {}
func Auth() {}
func First() {}
func Second() {}
''',
    })
    assert 'route:GET /api/users/:id' in ids(gin_rows), ids(gin_rows)
    gin_text = text_for(gin_rows, 'route:GET /api/users/:id')
    assert 'First' in gin_text and 'Second' in gin_text, gin_text
    assert 'func GetUser' in gin_text, gin_text

    echo_rows = run_fixture({
        'routes.go': '''package fixtures
import "github.com/labstack/echo/v4"
func routes() {
 e := echo.New()
 g := e.Group("/api", Auth)
 g.GET("/users/:id", GetUser, RequireAdmin)
}
func GetUser() {}
func Auth() {}
func RequireAdmin() {}
''',
    })
    assert 'route:GET /api/users/:id' in ids(echo_rows), ids(echo_rows)
    echo_text = text_for(echo_rows, 'route:GET /api/users/:id')
    assert 'func GetUser' in echo_text, echo_text
    assert 'RequireAdmin' in echo_text, echo_text
    assert 'func GetUser' in gin_text, gin_text

    mux_rows = run_fixture({
        'routes.go': '''package fixtures
import "github.com/gorilla/mux"
func routes() {
 r := mux.NewRouter()
 r.HandleFunc("/login", Login).Methods("POST")
 api := r.PathPrefix("/api").Subrouter()
 api.Path("/roles").HandlerFunc(GetRoles).Methods("GET", "HEAD")
}
func Login() {}
func GetRoles() {}
''',
    })
    assert 'route:POST /login' in ids(mux_rows), ids(mux_rows)
    assert 'route:GET /api/roles' in ids(mux_rows), ids(mux_rows)
    assert 'route:HEAD /api/roles' in ids(mux_rows), ids(mux_rows)

    helper_rows = run_fixture({
        'routes.go': '''package fixtures
import "github.com/gin-gonic/gin"
func register(g *gin.RouterGroup) {
 g.POST("/x", Handler)
}
func setup() {
 r := gin.New()
 api := r.Group("/api")
 register(api)
}
func Handler() {}
''',
    })
    assert 'route:POST /api/x' in ids(helper_rows), ids(helper_rows)

    print('golden extractor tests: ok')


if __name__ == '__main__':
    main()
