#!/bin/bash -eu
cd "$SRC/libiec61850"
mkdir -p build
cd build
cmake .. -DBUILD_EXAMPLES=OFF
make -j"$(nproc)"
INC="$(find ../src ../hal -name '*.h' -not -path '*/vs/*' -printf '-I%h\n' | sort -u) -Iconfig -I../config"
$CC $CFLAGS -include stdbool.h $LIB_FUZZING_ENGINE ../fuzz/fuzz_goose_subscriber.c -c -o fuzz_goose_subscriber.o $INC
$CXX $CXXFLAGS -fuse-ld=lld $LIB_FUZZING_ENGINE fuzz_goose_subscriber.o -o "$OUT/fuzz_goose_subscriber" ./src/libiec61850.a ./hal/libhal.a
