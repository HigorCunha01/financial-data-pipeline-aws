#!/usr/bin/env bash
# Gera .build/layer/python com as dependências da Lambda (requirements.txt),
# baixando os pacotes compilados para Linux x86_64 (runtime da Lambda).
#
# Uso (na pasta terraform):  ./build_layer.sh
set -euo pipefail

cd "$(dirname "$0")"
rm -rf .build/layer/python

python3 -m pip install \
  -r ../requirements.txt \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.13 \
  --only-binary=:all: \
  --target .build/layer/python \
  --upgrade

echo "Layer gerada em $(pwd)/.build/layer/python"
