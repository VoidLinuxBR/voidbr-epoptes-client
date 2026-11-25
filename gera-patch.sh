#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
#  gera-patch.sh — mantem o .patch do pacote em pkgfile/ (Void) e pkgbuild/
#                  (Arch) iguais e com o sha256sums certo nas duas receitas
#  Created: ter 24 nov 2026 19:56:59 -04
#  Updated: ter 24 nov 2026 19:56:59 -04
#
#  Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#
#  Uso (na raiz do repositorio):
#    ./gera-patch.sh aplicar    aplica o patch atual na arvore (usr/ etc/ opt/)
#                               para voce editar os arquivos em cima dele
#    ./gera-patch.sh gerar      gera o patch novo a partir das mudancas na
#                               arvore, grava em pkgfile/ e pkgbuild/, troca o
#                               sha256 no PKGFILE e no PKGBUILD e devolve a
#                               arvore ao estado do repositorio
#    ./gera-patch.sh conferir   confere: patch aplica, as duas copias sao
#                               iguais e o sha256 bate nas duas receitas

declare _VERSION_="1.0.0-20261124"
declare -a dirs=(usr etc opt)

red=$'\e[31m'
green=$'\e[32m'
yellow=$'\e[33m'
reset=$'\e[0m'

die() {
	echo "${red}ERRO:${reset} $*" >&2
	exit 1
}

ok() {
	echo "${green}[OK]${reset} $*"
}

existing_dirs() {
	local d
	for d in "${dirs[@]}"; do
		[[ -d $d ]] && echo "$d"
	done
}

find_patch() {
	local -a found
	found=(pkgfile/*.patch)
	[[ -e ${found[0]} ]] || die "nenhum pkgfile/*.patch encontrado"
	((${#found[@]} == 1)) || die "mais de um patch em pkgfile/: ${found[*]}"
	patch_name=${found[0]#pkgfile/}
	pkgfile_patch=pkgfile/$patch_name
	pkgbuild_patch=pkgbuild/$patch_name
}

tree_is_clean() {
	git diff --quiet -- $(existing_dirs)
}

restore_tree() {
	git checkout -q -- $(existing_dirs)
	find $(existing_dirs) -type d -name __pycache__ -exec sh -c \
		'git ls-files --error-unmatch "$1" >/dev/null 2>&1 || rm -rf "$1"' _ {} \; -prune
}

cmd_aplicar() {
	tree_is_clean || die "a arvore ja tem mudancas; rode './gera-patch.sh gerar' ou descarte-as"
	git apply "$pkgfile_patch" || die "o patch nao aplica"
	ok "patch aplicado; edite os arquivos e depois rode: ./gera-patch.sh gerar"
}

cmd_gerar() {
	local old new tmp
	tree_is_clean && die "a arvore nao tem mudancas; rode './gera-patch.sh aplicar' antes"
	tmp=$(mktemp)
	git diff -- $(existing_dirs) >"$tmp"
	old=$(sha256sum "$pkgfile_patch" | cut -d' ' -f1)
	new=$(sha256sum "$tmp" | cut -d' ' -f1)
	install -m644 "$tmp" "$pkgfile_patch"
	install -m644 "$tmp" "$pkgbuild_patch"
	rm -f "$tmp"
	sed -i "s/$old/$new/" pkgfile/PKGFILE pkgbuild/PKGBUILD
	restore_tree
	ok "patch gerado em $pkgfile_patch e $pkgbuild_patch"
	ok "sha256 $new no PKGFILE e no PKGBUILD"
	cmd_conferir
}

cmd_conferir() {
	local sum erros=0
	tree_is_clean || die "a arvore tem mudancas; rode './gera-patch.sh gerar' antes de conferir"
	if git apply --check "$pkgfile_patch" 2>/dev/null; then
		ok "o patch aplica limpo"
	else
		echo "${red}[FALHA]${reset} o patch nao aplica"; ((erros++))
	fi
	if cmp -s "$pkgfile_patch" "$pkgbuild_patch"; then
		ok "pkgfile/ e pkgbuild/ tem o mesmo patch"
	else
		echo "${red}[FALHA]${reset} $pkgfile_patch e $pkgbuild_patch sao diferentes"; ((erros++))
	fi
	sum=$(sha256sum "$pkgfile_patch" | cut -d' ' -f1)
	for f in pkgfile/PKGFILE pkgbuild/PKGBUILD; do
		if grep -q "$sum" "$f"; then
			ok "sha256 confere em $f"
		else
			echo "${red}[FALHA]${reset} sha256 $sum nao esta em $f"; ((erros++))
		fi
	done
	((erros == 0)) || die "$erros problema(s)"
}

cd "$(git rev-parse --show-toplevel 2>/dev/null)" || die "rode dentro do repositorio"
find_patch
case "$1" in
aplicar) cmd_aplicar ;;
gerar) cmd_gerar ;;
conferir) cmd_conferir ;;
-V | --version) echo "$_VERSION_" ;;
*) sed -n '/^#  Uso/,/^$/s/^#  \{0,1\}//p' "$0"; exit 1 ;;
esac
