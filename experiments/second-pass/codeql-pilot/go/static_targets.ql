import go
import semmle.go.dataflow.DataFlow

from DataFlow::CallNode call, FuncDef caller, Function callee
where
  caller = call.asExpr().getEnclosingFunction() and
  callee = call.getTarget() and
  call.asExpr().getFile().getRelativePath() = "encoding.go"
select
  caller.getName(),
  callee.getName(),
  call.asExpr().getFile().getRelativePath(),
  call.asExpr().getLocation().getStartLine(),
  call.asExpr().getLocation().getEndLine()
