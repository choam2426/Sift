import rust

from Call call, Function caller, Function callee
where
  caller = call.getEnclosingCallable() and
  callee = call.getStaticTarget() and
  call.getFile().getRelativePath() = "src/entry.rs"
select
  caller.getName().getText(),
  callee.getName().getText(),
  call.getFile().getRelativePath(),
  call.getLocation().getStartLine(),
  call.getLocation().getEndLine()
