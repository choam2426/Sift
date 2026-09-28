#include <string.h>

#define HEADER_SIZE 4

static unsigned read_length(const unsigned char *p)
{
    return (unsigned)p[0] << 8 | p[1];
}

int decode_block(unsigned char *out, size_t out_size, const unsigned char *in, size_t in_size)
{
    unsigned length;
    if (in_size < HEADER_SIZE)
        return -1;
    length = read_length(in);
    memcpy(out, in + HEADER_SIZE, length);
    return (int)length;
}

char *
find_marker(char *buffer, size_t size)
{
    return memchr(buffer, 0xff, size);
}

typedef int (*handler)(const unsigned char *, size_t);

int dispatch(handler h, const unsigned char *in, size_t size)
{
  return h(in, size);
}
