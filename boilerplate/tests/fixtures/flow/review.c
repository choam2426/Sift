#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Cases from the 2026-10-09 and 2026-10-11 reviews. Every function has a `noise` value no
   sink reads, and where it can, writes the sink's memory again after the sink (`after`):
   a flow-insensitive or one-class analysis would include those lines. */

struct buf { int len; int *d; };
struct ctx { int len; struct buf *b; };

int copy_then_write(const int *a, int *y, int n)
{
    int noise = n * 3;
    int *x = y;
    *y = n;
    int r = a[*x];
    *y = noise; /* after */
    return r;
}

int array_alias(const int *a, int n)
{
    int noise = n * 3;
    int buf[4];
    int *p = buf;
    buf[1] = n;
    int r = a[p[1]];
    buf[1] = noise; /* after */
    return r;
}

void init2(struct ctx *c, int n)
{
    int noise = n * 3;
    struct ctx *e = c;
    e->len = n;
}

int alias_in_callee(const int *a, struct ctx *c, int n)
{
    int noise = n * 3;
    init2(c, n);
    int r = a[c->len];
    init2(c, noise); /* after */
    return r;
}

void init3(struct ctx *c, int n)
{
    struct buf *b = c->b;
    b->len = n;
}

int field_alias_in_callee(const int *a, struct ctx *c, int n)
{
    int noise = n * 3;
    init3(c, n);
    int r = a[c->b->len];
    init3(c, noise); /* after */
    return r;
}

void fill(int *p, int n)
{
    *p = n;
}

int conditional_argument(const int *a, int *p, int *q, int c, int n)
{
    int noise = n * 3;
    fill(c ? p : q, n);
    int r = a[*p];
    fill(p, noise); /* after */
    return r;
}

struct ctx *get(void);

int same_callee_results(const int *a, int n)
{
    int noise = n * 3;
    get()->len = n;
    int r = a[get()->len];
    get()->len = noise; /* after */
    return r;
}

int increment_keeps_writes(const int *arr, int *p, int n)
{
    int noise = n * 3;
    p[1] = n;
    p++;
    int r = arr[p[0]];
    p[0] = noise; /* after */
    return r;
}

void w2(int *p, int n)
{
    p[1] = n;
    p++;
}

int increment_in_callee(const int *arr, int *p, int n)
{
    int noise = n * 3;
    w2(p, n);
    int r = arr[p[1]];
    w2(p, noise); /* after */
    return r;
}

int struct_copy(const int *a, struct buf *p, int n)
{
    int noise = n * 3;
    p->d[0] = n;
    struct buf t = *p;
    int r = a[t.d[0]];
    p->d[0] = noise; /* after */
    return r;
}

static int use3(struct buf t, const int *a)
{
    return a[t.d[0]];
}

int struct_argument(const int *a, struct buf *p, int n)
{
    int noise = n * 3;
    p->d[0] = n;
    int r = use3(*p, a);
    p->d[0] = noise; /* after */
    return r;
}

static struct buf ret3(struct buf *p)
{
    return *p;
}

int struct_return(const int *a, struct buf *p, int n)
{
    int noise = n * 3;
    p->d[0] = n;
    struct buf t = ret3(p);
    int r = a[t.d[0]];
    p->d[0] = noise; /* after */
    return r;
}

int read_with_scanf(const int *a)
{
    int noise = 3;
    int n = 0;
    scanf("%d", &n);
    int r = a[n];
    n = noise; /* after */
    return r;
}

typedef int (*op_fn)(int);

static int hidden(int v)
{
    return v + 1;
}

static int other(int v)
{
    return v;
}

op_fn g_other = other;

int static_table(const int *a, int w, int v)
{
    int noise = v * 3;
    static const op_fn table[] = { hidden };
    int r = a[table[w](v)];
    v = noise; /* after */
    return r;
}

int asm_output(const int *arr, int x)
{
    int noise = x * 3;
    int n = 0;
    __asm__("" : "=r"(n) : "r"(x));
    int r = arr[n];
    n = noise; /* after */
    return r;
}

int asm_elsewhere(const int *arr, int x)
{
    __asm__ volatile("nop");
    return arr[x];
}

int abort_guard(const int *a, int n)
{
    int noise = n * 3;
    if (n > 10)
        abort();
    int r = a[n];
    n = noise; /* after */
    return r;
}

static void fatal(const char *m)
{
    fprintf(stderr, "%s", m);
    exit(1);
}

int inferred_guard(const int *a, int n)
{
    int noise = n * 3;
    if (n > 10)
        fatal("too big");
    int r = a[n];
    n = noise; /* after */
    return r;
}

int switch_arms(const int *a, int n, int k)
{
    int noise = n * 3;
    int at = 0;
    switch (k) {
    case 1:
        at = n;
        break;
    case 2:
        goto out;
    }
    int r = a[at];
    at = noise; /* after */
    return r;
out:
    return 0;
}

void fortified(char *d, size_t k, const char *fmt)
{
    snprintf(d, k, fmt);
}

static int level;

static void down(int n)
{
    if (n > 0) {
        level = n;
        down(n - 1);
    }
}

int recursion_writes_global(const int *a, int n)
{
    int noise = n * 3;
    level = 0;
    down(n);
    int r = a[level];
    level = noise; /* after */
    return r;
}

struct n4 { struct n4 *next; int v; };

static int deep(struct n4 *p)
{
    return p->next->next->v;
}

int widening(const int *a, struct n4 *q, int i)
{
    int x = a[i];
    return a[deep(q->next->next)] + x;
}

int for_comment(const int *a, int n)
{
    int i, s = 0;
    for (i = 0; /* ; */ i < n;)
        s += a[i++];
    return s;
}

static int shared, other_shared;

static int many(int x, int y, int z)
{
    return x + y + z + shared + other_shared;
}

int seed_order(const int *a, int n)
{
    int base = n * 7;
    int u = base + 1;
    int w = base + 2;
    int t = base + 3;
    shared = base + 4;
    other_shared = base + 5;
    return a[many(u, w, t)];
}

/* R1: a plain write to one of several objects a pointer may name is weak */
int strong_two_locals(const int *arr, int c, int secret)
{
    int noise = secret * 3;
    int x = secret, y = 1;
    int *q = c ? &x : &y;
    y = 0;
    int r = arr[x];
    x = noise; /* after */
    return r;
}

int param_in_class(const int *arr, int c, int n)
{
    int x = 1;
    int *q = c ? &n : &x;
    x = 0;
    return arr[n];
}

static int g_lo, g_hi, unrelated;

static void set_lo(int v)
{
    g_lo = v;
}

static int globals_in_class(const int *arr, int c)
{
    int noise = c * 3;
    int *p = c ? &g_lo : &g_hi;
    g_hi = 0;
    int r = arr[g_lo];
    unrelated = noise; /* after: a global's own later write reaches its next call */
    return r;
}

int call_globals_in_class(const int *arr, int v)
{
    set_lo(v);
    return globals_in_class(arr, 0);
}

/* R2: a global written through a local pointer */
static int counter;

static void set_through_local(int n)
{
    int noise = n * 3;
    int *p = &counter;
    *p = n;
}

int read_counter(const int *arr)
{
    return arr[counter];
}

void call_set_and_read(const int *arr, int n)
{
    set_through_local(n);
    read_counter(arr);
}

/* R3: a pointer to a pointer */
int ptr_to_ptr(const int *arr, int n)
{
    int noise = n * 3;
    int x = 0;
    int *p = 0;
    int **pp = &p;
    *pp = &x;
    x = n;
    int r = arr[*p];
    x = noise; /* after */
    return r;
}

/* R4: a returned pointer into an argument */
static unsigned char *skip_one(unsigned char *p)
{
    return p + 1;
}

int returned_into_argument(const int *arr, int n)
{
    int noise = n * 3;
    unsigned char buf[8] = {0};
    unsigned char *q = skip_one(buf);
    *q = n;
    int r = arr[buf[1]];
    *q = noise; /* after */
    return r;
}

int returned_by_model(const int *arr, char *s, int n)
{
    int noise = n * 3;
    char *e = strchr(s, ':');
    *e = n;
    int r = arr[s[3]];
    *e = noise; /* after */
    return r;
}

struct item { int v; };
struct box { int head; struct item it; };

static struct item *inner_item(struct box *b)
{
    return &b->it;
}

int returned_into_member(const int *arr, struct box *b, int n)
{
    int noise = n * 3;
    struct item *p = inner_item(b);
    p->v = n;
    int r = arr[b->it.v];
    p->v = noise; /* after */
    return r;
}

struct line { int len; char text[16]; };

static char *text_of(struct line *l)
{
    return l->text;
}

int returned_into_buffer(const int *arr, struct line *l, int n)
{
    int noise = n * 3;
    char *t = text_of(l);
    t[2] = n;
    int r = arr[l->text[2]];
    t[2] = noise; /* after */
    return r;
}

/* R5: an address that leaves through a callee or a global */
struct holder { int *px; };

static void hold(struct holder *h, int *x)
{
    h->px = x;
}

static void fill_held(struct holder *h, int n)
{
    *h->px = n;
}

int escaped_through_callee(const int *arr, int n)
{
    int noise = n * 3;
    struct holder h;
    int x = 0;
    hold(&h, &x);
    fill_held(&h, n);
    int r = arr[x];
    fill_held(&h, noise); /* after */
    return r;
}

static int *kept;

static void keep(int *x)
{
    kept = x;
}

static void poke(int n)
{
    *kept = n;
}

int escaped_through_global(const int *arr, int n)
{
    int noise = n * 3;
    int x = 0;
    keep(&x);
    poke(n);
    int r = arr[x];
    poke(noise); /* after */
    return r;
}

/* R6: global writes two calls down, through a bounded component or a capped call */
static int depth_g;

static void ping(int n, int k);

static void pong(int n, int k)
{
    if (k)
        ping(n, k - 1);
}

static void ping(int n, int k)
{
    if (k)
        pong(n, k - 1);
    else
        depth_g = n;
}

static void enter(int n)
{
    ping(n, 3);
}

int two_levels_up(const int *arr, int n)
{
    int noise = n * 3;
    depth_g = 0;
    enter(n);
    int r = arr[depth_g];
    unrelated = noise; /* after */
    return r;
}

static int disp_g;

static void handler_a(int x)
{
    disp_g = x;
}

static void handler_b(int x)
{
    disp_g = x + 1;
}

static void (*handlers[])(int) = { handler_a, handler_b };

static void dispatch_one(int w, int x)
{
    handlers[w](x);
}

int through_dispatch(const int *arr, int w, int x)
{
    int noise = x * 3;
    disp_g = 0;
    dispatch_one(w, x);
    int r = arr[disp_g];
    unrelated = noise; /* after */
    return r;
}

/* P1: a caller passes one object for two pointer parameters */
static int both_ptrs(const int *arr, int *p, int *q, int n)
{
    int noise = n * 3;
    *p = n;
    return arr[*q];
}

int same_object_twice(const int *arr, int n)
{
    int x = 0;
    return both_ptrs(arr, &x, &x, n);
}

/* P2: a callee that aborts depending on its argument */
static void check_or_abort(int c)
{
    if (c)
        abort();
}

int conditional_abort(const int *arr, int c, int n)
{
    int noise = n * 3;
    int k = n;
    check_or_abort(c);
    int r = arr[k];
    k = noise; /* after */
    return r;
}
