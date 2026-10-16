import cpp

from Call call, Function caller
where
  caller = call.getEnclosingFunction() and
  not exists(call.getTarget())
select
  caller.getLocation().getFile().getRelativePath(),
  caller.getLocation().getStartLine(),
  caller.getName(),
  call.getFile().getRelativePath(),
  call.getLocation().getStartLine(),
  call.getLocation().getEndLine()
