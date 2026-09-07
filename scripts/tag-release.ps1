# 校验 __version__ 后创建并推送 tag，由 GitHub Actions 自动打包 Release。
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$ver = python -c "from app import __version__; print(__version__)"
if (-not $ver) { throw "无法读取 app.__version__" }
$tag = "v$ver"

Write-Host "version=$ver tag=$tag"

$status = git status --porcelain
if ($status -and -not $Force) {
    Write-Host "工作区有未提交改动，请先 commit，或加 -Force："
    git status -sb
    exit 1
}

$existing = git tag -l $tag
if ($existing) {
    throw "本地已存在 tag $tag，请先升版本号或删除旧 tag"
}

git tag -a $tag -m $tag
git push origin $tag
Write-Host "已推送 $tag，请到 Actions 查看打包进度。"
