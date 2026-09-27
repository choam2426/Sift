import cpp
import semmle.code.cpp.dataflow.new.DataFlow
import semmle.code.cpp.dataflow.new.TaintTracking

// Transitive local flow into a field or dereferenced-pointer assignment.
// This is a data relationship, not a claim that any assignment is unsafe.
from Assignment effect, Expr input, Expr output, DataFlow::Node source,
  DataFlow::Node sink, Function enclosing, string kind
where
  enclosing = effect.getEnclosingFunction() and
  enclosing.getLocation().getFile().getRelativePath() = "C/XzDec.c" and
  (effect.getLValue() instanceof FieldAccess or
   effect.getLValue() instanceof PointerDereferenceExpr) and
  output = effect.getRValue().getAChild*() and
  sink.asExpr() = output and
  source.asExpr() = input and
  input.getEnclosingFunction() = enclosing and
  input.getLocation().getFile().getRelativePath() = "C/XzDec.c" and
  output.getLocation().getFile().getRelativePath() = "C/XzDec.c" and
  input.getLocation().getStartLine() < output.getLocation().getStartLine() and
  (
    kind = "exact_value" and DataFlow::localFlow(source, sink)
    or
    kind = "taint_influence" and TaintTracking::localTaint(source, sink) and
    not DataFlow::localFlow(source, sink)
  )
select
  enclosing.getLocation().getFile().getRelativePath(),
  enclosing.getLocation().getStartLine(),
  enclosing.getName(),
  kind,
  input.getLocation().getStartLine(),
  input.getLocation().getStartColumn(),
  input.getLocation().getEndLine(),
  input.getLocation().getEndColumn(),
  output.getLocation().getStartLine(),
  output.getLocation().getStartColumn(),
  output.getLocation().getEndLine(),
  output.getLocation().getEndColumn(),
  effect.getLocation().getStartLine(),
  effect.getLocation().getStartColumn(),
  effect.getLocation().getEndLine(),
  effect.getLocation().getEndColumn()
