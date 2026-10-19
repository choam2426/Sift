#!/bin/bash -eu
# Derived from google/oss-fuzz projects/md4c/build.sh at
# 7557a340dce971f0bf3d430a240046f8012506ff. The OSS-Fuzz script moves a
# seed-corpus zip and a dictionary out of $SRC, which needs files this recipe
# does not vendor; this version keeps the compile steps and stays idempotent so
# the agent can rerun `compile` inside the container.
cd "$SRC/md4c"
mkdir -p build
cd build
cmake .. -DBUILD_SHARED_LIBS=OFF
make -j"$(nproc)"
$CC $CFLAGS -c ../test/fuzzers/fuzz-mdhtml.c -I../src
$CXX $CXXFLAGS $LIB_FUZZING_ENGINE fuzz-mdhtml.o -o $OUT/fuzz-mdhtml \
    ./src/libmd4c-html.a ./src/libmd4c.a
