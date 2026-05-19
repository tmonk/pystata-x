# CMake generated Testfile for 
# Source directory: /Users/tom/projects/pystata-x/src/stata-fast
# Build directory: /Users/tom/projects/pystata-x/src/stata-fast/build2
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test([=[compile_check]=] "/Users/tom/projects/pystata-x/src/stata-fast/build2/compile_check")
set_tests_properties([=[compile_check]=] PROPERTIES  WORKING_DIRECTORY "/Users/tom/projects/pystata-x/src/stata-fast/build2" _BACKTRACE_TRIPLES "/Users/tom/projects/pystata-x/src/stata-fast/CMakeLists.txt;104;add_test;/Users/tom/projects/pystata-x/src/stata-fast/CMakeLists.txt;0;")
add_test([=[test_stata_fast]=] "/Users/tom/projects/pystata-x/src/stata-fast/build2/test_stata_fast")
set_tests_properties([=[test_stata_fast]=] PROPERTIES  ENVIRONMENT "STATA_PATH=/Applications/StataNow;STATA_EDITION=se" SKIP_RETURN_CODE "77" WORKING_DIRECTORY "/Users/tom/projects/pystata-x/src/stata-fast/build2" _BACKTRACE_TRIPLES "/Users/tom/projects/pystata-x/src/stata-fast/CMakeLists.txt;123;add_test;/Users/tom/projects/pystata-x/src/stata-fast/CMakeLists.txt;0;")
