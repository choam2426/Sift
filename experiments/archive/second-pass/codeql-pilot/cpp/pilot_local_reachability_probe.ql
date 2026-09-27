import cpp
import semmle.code.cpp.dataflow.new.DataFlow
import semmle.code.cpp.dataflow.new.TaintTracking

// Probe whether transitive local flow reaches the pilot's value sites.
from DataFlow::Node source, DataFlow::Node sink, Expr fromExpr, Expr toExpr,
  Function enclosing, string kind
where
  fromExpr = source.asExpr() and
  toExpr = sink.asExpr() and
  enclosing = fromExpr.getEnclosingFunction() and
  enclosing = toExpr.getEnclosingFunction() and
  enclosing.getName() = "MixCoder_Code" and
  enclosing.getLocation().getFile().getRelativePath() = "C/XzDec.c" and
  fromExpr.getLocation().getStartLine() in [585 .. 652] and
  toExpr.getLocation().getStartLine() in [606 .. 652] and
  fromExpr != toExpr and
  (
    kind = "exact_value" and DataFlow::localFlow(source, sink)
    or
    kind = "taint_influence" and TaintTracking::localTaint(source, sink) and
    not DataFlow::localFlow(source, sink)
  )
select
  kind,
  fromExpr.getLocation().getStartLine(),
  fromExpr.getLocation().getStartColumn(),
  fromExpr.getLocation().getEndLine(),
  fromExpr.getLocation().getEndColumn(),
  toExpr.getLocation().getStartLine(),
  toExpr.getLocation().getStartColumn(),
  toExpr.getLocation().getEndLine(),
  toExpr.getLocation().getEndColumn()
