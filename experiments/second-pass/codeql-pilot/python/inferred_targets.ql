import python
import semmle.python.types.FunctionObject

from FunctionObject callee, CallNode call, Function caller
where
  call = callee.getACall() and
  caller = call.getScope() and
  call.getLocation().getFile().getRelativePath() = "src/urllib3/response.py"
select
  caller.getName(),
  callee.getQualifiedName(),
  call.getLocation().getFile().getRelativePath(),
  call.getLocation().getStartLine(),
  call.getLocation().getEndLine()
