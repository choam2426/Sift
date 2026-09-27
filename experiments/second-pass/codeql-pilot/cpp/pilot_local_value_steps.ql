import cpp
import semmle.code.cpp.dataflow.new.DataFlow
import semmle.code.cpp.dataflow.new.TaintTracking

// Neutral, intra-function value/taint propagation steps in the pilot source.
// A taint step can express influence through an arithmetic operation; it is
// weaker than an exact-value flow and must be labelled separately.
from DataFlow::Node source, DataFlow::Node sink, Expr fromExpr, Expr toExpr,
  Function enclosing, string kind
where
  fromExpr = source.asExpr() and
  toExpr = sink.asExpr() and
  enclosing = fromExpr.getEnclosingFunction() and
  enclosing = toExpr.getEnclosingFunction() and
  enclosing.getLocation().getFile().getRelativePath() = "C/XzDec.c" and
  fromExpr.getLocation().getFile().getRelativePath() = "C/XzDec.c" and
  toExpr.getLocation().getFile().getRelativePath() = "C/XzDec.c" and
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
