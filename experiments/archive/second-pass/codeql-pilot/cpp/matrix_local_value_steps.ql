import cpp
import semmle.code.cpp.dataflow.new.DataFlow
import semmle.code.cpp.dataflow.new.TaintTracking

// Neutral, local value influence in the C source scope. Taint influence is
// weaker than exact value flow; neither is an interprocedural path.
from DataFlow::Node source, DataFlow::Node sink, Expr fromExpr, Expr toExpr,
  Function enclosing, string kind
where
  fromExpr = source.asExpr() and
  toExpr = sink.asExpr() and
  enclosing = fromExpr.getEnclosingFunction() and
  enclosing = toExpr.getEnclosingFunction() and
  enclosing.getLocation().getFile().getRelativePath().regexpMatch("C/.*") and
  fromExpr.getLocation().getFile().getRelativePath().regexpMatch("C/.*") and
  toExpr.getLocation().getFile().getRelativePath().regexpMatch("C/.*") and
  (
    kind = "exact_value" and DataFlow::localFlowStep(source, sink)
    or
    kind = "taint_influence" and TaintTracking::localTaintStep(source, sink) and
    not DataFlow::localFlowStep(source, sink)
  )
select
  enclosing.getLocation().getFile().getRelativePath(),
  enclosing.getLocation().getStartLine(),
  enclosing.getName(),
  kind,
  fromExpr.getLocation().getStartLine(),
  fromExpr.getLocation().getStartColumn(),
  fromExpr.getLocation().getEndLine(),
  fromExpr.getLocation().getEndColumn(),
  toExpr.getLocation().getStartLine(),
  toExpr.getLocation().getStartColumn(),
  toExpr.getLocation().getEndLine(),
  toExpr.getLocation().getEndColumn()
