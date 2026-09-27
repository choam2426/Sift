import cpp

// Definition locations identify the first-pass functions; names alone do not.
from FunctionCall call, Function caller, Function callee
where
  caller = call.getEnclosingFunction() and
  callee = call.getTarget()
select
  caller.getLocation().getFile().getRelativePath(),
  caller.getLocation().getStartLine(),
  caller.getName(),
  callee.getLocation().getFile().getRelativePath(),
  callee.getLocation().getStartLine(),
  callee.getName(),
  call.getFile().getRelativePath(),
  call.getLocation().getStartLine(),
  call.getLocation().getEndLine()
