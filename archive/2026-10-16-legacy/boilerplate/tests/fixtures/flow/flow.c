#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

/* if/else with a short-circuit guard and an early exit */
int guarded(const unsigned char *buf, size_t n, int i)
{
    if (i < 0 || (size_t)i >= n)
        return -1;
    else
        return buf[i];
}

/* while with continue and break */
int scan_until(const char *s, int limit)
{
    int i = 0;
    while (i < limit) {
        if (s[i] == ' ') {
            i++;
            continue;
        }
        if (s[i] == 0)
            break;
        i++;
    }
    return s[i];
}

/* do-while */
int sum_down(const int *v, int n)
{
    int total = 0;
    do {
        n--;
        total += v[n];
    } while (n > 0);
    return total;
}

/* for loops with omitted parts */
int first_zero(const int *v, int n)
{
    int i = 0;
    for (;;) {
        if (i >= n)
            return -1;
        if (v[i] == 0)
            break;
        i++;
    }
    for (; i < n;)
        i++;
    return v[i - 1];
}

/* switch with fallthrough and default */
int by_kind(const unsigned char *p, int kind)
{
    int at = 0;
    switch (kind) {
    case 1:
        at = 4;
        /* fall through */
    case 2:
        at += 2;
        break;
    default:
        at = 8;
    }
    return p[at];
}

/* goto error handling */
int parse_header(const unsigned char *p, size_t n, unsigned *out)
{
    unsigned len;
    if (n < 4)
        goto fail;
    len = p[0] | p[1] << 8;
    if (len > n)
        goto fail;
    *out = p[len - 1];
    return 0;
fail:
    return -1;
}

/* conditional operator and comma */
int pick(const int *a, int i, int j)
{
    int k = (i > j) ? i : j;
    int m = (k++, k * 2);
    return a[m];
}

/* short-circuit value and nested blocks */
int nested(const int *a, int i, int n)
{
    int ok = i >= 0 && i < n;
    {
        {
            if (ok)
                return a[i];
        }
    }
    return 0;
}

/* field sensitivity across calls */
struct buffer {
    unsigned char *data;
    size_t len;
    size_t cap;
};

void set_len(struct buffer *b, size_t len)
{
    b->len = len;
}

void set_cap(struct buffer *b, size_t cap)
{
    b->cap = cap;
}

unsigned char last(struct buffer *b, size_t len, size_t cap)
{
    set_len(b, len);
    set_cap(b, cap);
    return b->data[b->len - 1];
}

/* slices that climb into callers and descend into callees */
static size_t clamp(size_t n, size_t max)
{
    return n > max ? max : n;
}

static unsigned char at(const unsigned char *p, size_t i)
{
    return p[i];
}

unsigned char use_at(const unsigned char *p, size_t n, size_t i)
{
    size_t j = clamp(i, n - 1);
    return at(p, j);
}

/* a callee writes through a pointer argument */
static void read_size(const unsigned char *p, size_t *size)
{
    *size = p[0];
}

void copy_block(unsigned char *dst, const unsigned char *src)
{
    size_t size;
    read_size(src, &size);
    memcpy(dst, src + 1, size);
}

/* indirect calls through a table of address-taken functions */
typedef size_t (*measure_fn)(const unsigned char *);

static size_t measure_short(const unsigned char *p)
{
    return p[0];
}

static size_t measure_long(const unsigned char *p)
{
    return (size_t)p[0] << 8 | p[1];
}

static const measure_fn measures[] = { measure_short, measure_long };

void copy_measured(unsigned char *dst, const unsigned char *src, int which)
{
    size_t n = measures[which](src);
    memcpy(dst, src, n);
}

/* library models: input from read(), a copy, and a callee with no model */
int read_record(int fd, unsigned char *out)
{
    unsigned char header[2];
    if (read(fd, header, 2) != 2)
        return -1;
    size_t n = header[0];
    memcpy(out, header, n);
    return 0;
}

extern size_t external_size(const unsigned char *p);

void copy_external(unsigned char *dst, const unsigned char *src)
{
    memcpy(dst, src, external_size(src));
}

/* integer conversions that feed a sink */
void narrow_copy(unsigned char *dst, const unsigned char *src, long n)
{
    int m = n;
    long unused = (short)n;
    memcpy(dst, src, m);
}

/* globals written by one callee and read by another */
static size_t limit = 64;

void set_limit(size_t n)
{
    limit = n;
}

unsigned char read_limited(const unsigned char *p)
{
    return p[limit];
}

unsigned char configure_and_read(const unsigned char *p, size_t n)
{
    set_limit(n);
    return read_limited(p);
}

/* a check only one configuration compiles */
size_t copy_name(char *dst, const char *src, size_t n)
{
#ifdef _WIN32
    if (n > 16)
        return 0;
#endif
    memcpy(dst, src, n);
    return n;
}

/* recursion */
static size_t depth(const unsigned char *p, size_t n)
{
    if (n == 0)
        return 0;
    return 1 + depth(p + 1, n - 1);
}

/* an address stored in a pointer: aliasing the analysis does not follow */
int alias(const int *a, int n)
{
    int x = 0;
    int *q = &x;
    *q = n;
    return a[x];
}

/* a fuzzer entry point */
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    unsigned out;
    if (parse_header(data, size, &out) == 0)
        return (int)depth(data, size);
    return 0;
}
