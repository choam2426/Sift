#include <string.h>

/* a container just big enough for range-for */
struct Sizes {
    const int *items;
    int count;
    const int *begin() const { return items; }
    const int *end() const { return items + count; }
};

struct Reader {
    Sizes sizes;
    int total() const;
};

int Reader::total() const
{
    int t = 0;
    for (int s : sizes)
        t += s;
    return t;
}

void fill(char *dst, const Reader &r)
{
    int n = r.total();
    memset(dst, 0, n);
}

int guarded_at(const int *buf, int n, int i)
{
    try {
        if (i >= n)
            throw n;
        return buf[i];
    } catch (int e) {
        return -e;
    }
}

int init_if(const int *a, int n)
{
    int k = 0;
    if (k = n * 2; n > 10)
        return 0;
    return a[k];
}
