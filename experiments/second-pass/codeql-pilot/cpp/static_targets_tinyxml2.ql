import cpp

from FunctionCall call, Function caller, Function callee
where
  caller = call.getEnclosingFunction() and
  callee = call.getTarget() and
  call.getFile().getRelativePath() = "tinyxml2.cpp"
select
  caller.getQualifiedName(),
  callee.getQualifiedName(),
  call.getFile().getRelativePath(),
  call.getLocation().getStartLine(),
  call.getLocation().getEndLine()
