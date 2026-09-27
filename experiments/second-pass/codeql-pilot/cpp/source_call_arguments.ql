import cpp

// Extract statically resolved call arguments without assigning security meaning.
from FunctionCall call, Function caller, Function callee, int index, Expr argument
where
  caller = call.getEnclosingFunction() and
  callee = call.getTarget() and
  argument = call.getArgument(index) and
  call.getFile().getRelativePath() = "C/XzDec.c"
select
  caller.getLocation().getStartLine(),
  caller.getName(),
  callee.getLocation().getFile().getRelativePath(),
  callee.getLocation().getStartLine(),
  callee.getName(),
  call.getLocation().getStartLine(),
  call.getLocation().getStartColumn(),
  index,
  argument.getLocation().getStartLine(),
  argument.getLocation().getStartColumn(),
  argument.getLocation().getEndLine(),
  argument.getLocation().getEndColumn(),
  argument.toString()
