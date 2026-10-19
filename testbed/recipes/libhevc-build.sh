#!/bin/bash -eu
cd "$SRC/libhevc"
# Some revisions call libhevc_add_gtest() unconditionally, which fetches
# googletest at configure time. The build container has no network. The
# ENABLE_TESTS option exists only in later revisions; the sed handles the
# earlier unconditional call.
sed -i 's/^libhevc_add_gtest()/# libhevc_add_gtest()/' CMakeLists.txt
sed -i 's|^include("${HEVC_ROOT}/tests/common/common.cmake")|# tests need googletest|' CMakeLists.txt
mkdir -p "$WORK/build"
cd "$WORK/build"
cmake -DENABLE_TESTS=OFF "$SRC/libhevc"
make -j"$(nproc)" hevc_dec_fuzzer
cp hevc_dec_fuzzer "$OUT/hevc_dec_fuzzer"
