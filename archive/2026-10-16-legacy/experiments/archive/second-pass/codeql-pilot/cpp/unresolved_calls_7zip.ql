import cpp

from Call call
where
  call.getFile().getRelativePath() = "C/XzDec.c" and
  not exists(call.getTarget())
select
  call.getFile().getRelativePath(),
  call.getLocation().getStartLine(),
  call.getLocation().getEndLine()
