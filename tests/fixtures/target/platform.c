#define PRF_STR(s)
#define NO_INLINE

#ifdef _WIN32
static int read_random(void)
{
  return 1;
}
#else
static int read_random(void)
{
  PRF_STR("posix")
  return 2;
}
#endif

#ifdef SIFT_FEATURE
int feature(void)
{
  return read_random();
}
#endif

#if 0
int disabled(void)
{
  return 0;
}
#endif

NO_INLINE
int after_macros(int x)
{
  PRF_STR("x")
  return x + read_random();
}

#  ifdef SIFT_SPACED
int spaced(void) { return 1; }
#  endif

#ifdef SIFT_OUTER
#ifdef	SIFT_INNER
int nested(void)
{
#ifdef SIFT_DEBUG
  PRF_STR("debug")
#endif
  return 1;
}
#endif
#endif
