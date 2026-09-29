# 💰 Pipeline Serverless de Dados Financeiros — AWS

![CI](https://github.com/HigorCunha01/financial-data-pipeline-aws/actions/workflows/ci.yml/badge.svg)

Pipeline de dados serverless que extrai indicadores econômicos (Selic, IPCA e câmbio)
da API pública do Banco Central do Brasil, valida a qualidade do dado e o
disponibiliza para consulta via SQL — sem nenhum banco de dados tradicional rodando,
usando S3, Glue Data Catalog e Athena.

O projeto foi construído em duas fases:

- **Fase 1 — manual**: toda a arquitetura montada pelo console da AWS, para aprender
  cada serviço na prática (Lambda, Layers, S3, Glue Crawler, Athena, IAM).
- **Fase 2 — IaC + DataOps**: a mesma arquitetura reescrita em **Terraform**, agora
  rodando sozinha todo dia (**EventBridge Scheduler**), com **validação de qualidade
  de dado**, **alertas por e-mail** (CloudWatch + SNS), **testes automatizados**
  (pytest) e **CI no GitHub Actions**.

## Arquitetura

```
  ┌──────────────────────────┐
  │ EventBridge Scheduler     │  todo dia, 09:00 (America/Sao_Paulo)
  └────────────┬──────────────┘
               ▼
  ┌──────────────────────────┐        ┌──────────────────────────┐
  │ AWS Lambda  extract-bcb   │ ─────► │ API do Banco Central (SGS)│
  │ + Layer (requests)        │ ◄───── │ Selic, IPCA, Dólar        │
  │                           │        └──────────────────────────┘
  │ validação de qualidade    │
  └──────┬─────────────┬──────┘
         │ dado válido │ erro / dado inválido / não rodou
         ▼             ▼
  ┌───────────────┐  ┌──────────────────────────┐
  │ Amazon S3      │  │ CloudWatch Alarms → SNS   │ ──► e-mail de alerta
  │ raw/serie=.../ │  └──────────────────────────┘
  │ data_execucao= │
  └──────┬─────────┘
         ▼
  ┌──────────────────────────┐
  │ Glue Data Catalog         │  tabela declarada em Terraform +
  │ database financial_data   │  partition projection (sem crawler)
  └────────────┬──────────────┘
               ▼
  ┌──────────────────────────┐
  │ Amazon Athena             │  workgroup com limite de custo por query
  └──────────────────────────┘
```

## Stack

| Camada           | Ferramenta                                  |
|------------------|---------------------------------------------|
| Infraestrutura   | Terraform (IaC)                              |
| Agendamento      | Amazon EventBridge Scheduler                 |
| Extração         | Python (`requests`) em AWS Lambda            |
| Empacotamento    | AWS Lambda Layers (dependência separada do código) |
| Qualidade de dado| Validações em Python antes de gravar no S3   |
| Armazenamento    | Amazon S3 (particionado, JSON Lines)         |
| Catalogação      | AWS Glue Data Catalog (partition projection) |
| Consulta         | Amazon Athena                                |
| Monitoramento    | CloudWatch Logs + Alarms, Amazon SNS         |
| Testes / CI      | pytest, ruff, GitHub Actions                 |
| Permissões       | IAM com menor privilégio por serviço         |

## Por que essas escolhas

- **Serverless em vez de servidor fixo**: nada fica ligado 24h. A Lambda só roda
  quando o agendamento dispara, e o Athena só cobra na hora da query.
- **Particionamento por série e data** (`serie=selic/data_execucao=2026-09-29/`):
  reduz o volume escaneado a cada consulta no Athena — que cobra por dado lido.
- **JSON Lines em vez de array JSON**: um registro por linha, o que permite ler
  colunas reais (`data`, `valor`) em vez de uma única coluna `array`
  (ver Troubleshooting #1).
- **Lambda Layer para `requests`**: separa "código de negócio" de "biblioteca de
  terceiro". O script `build_layer` baixa os pacotes compilados para Linux, então
  a layer funciona mesmo gerada no Windows.
- **Partition projection em vez de Glue Crawler**: na Fase 1, um crawler inferia o
  schema e registrava as partições. Aqui o schema é declarado em código e o Athena
  calcula as partições sozinho a partir do padrão do caminho. Resultado: partição
  nova fica consultável na hora, schema versionado no Git e **custo zero** — um
  crawler rodando todo dia custaria alguns dólares por mês (cobrança mínima de 10
  minutos de DPU por execução).
- **Validação de qualidade dentro da Lambda**: cada série é checada antes de ir para
  o S3 (lista não vazia, campos obrigatórios, data no formato `dd/mm/aaaa`, valor
  numérico e finito, sem datas duplicadas). Série reprovada **não é gravada** e a
  execução termina com erro — o que dispara o alarme. Uma série com problema não
  impede as outras de serem gravadas. Optei por checagens próprias em vez de Great
  Expectations porque o volume é pequeno e a dependência pesaria na Lambda.
- **Janela de busca por série**: o IPCA é mensal (data de referência no dia 1º,
  publicado por volta do dia 10 do mês seguinte), então uma janela de 30 dias pode
  não conter nenhum ponto. Cada série tem sua própria janela (`dias`): 30 para Selic
  e dólar, 90 para IPCA. Uma resposta sem dados — inclusive o `404` que o SGS
  devolve quando o intervalo está vazio — é reprovada pela validação com mensagem
  clara, em vez de gerar um arquivo vazio no S3.
- **Dois alarmes, não um**: um para quando a extração **falha** e outro para quando
  ela **simplesmente não roda** por mais de 26h — o tipo de falha silenciosa que
  costuma passar despercebida por dias. A janela é de 26h, e não 24h cravadas,
  porque a execução diária cai sempre no mesmo horário: com 24h exatas o alarme
  dispararia alguns minutos todo dia, no intervalo entre a execução de ontem sair
  da janela e a métrica da execução de hoje chegar.
- **Sem retentativa automática**: a Lambda é configurada com 0 retentativas. Uma
  falha vira alerta na hora, e a execução do dia seguinte já cobre o período perdido,
  porque a janela de busca é móvel. Com o padrão da AWS (2 retentativas), uma única
  falha rodaria o pipeline três vezes.
- **FinOps**: limite de 100 MB escaneados por query no workgroup do Athena,
  resultados de query apagados após 7 dias, logs com retenção de 14 dias e tags
  `Project`/`ManagedBy` em todos os recursos para filtrar custo no Cost Explorer.
- **IAM com menor privilégio**: a Lambda só pode fazer `s3:PutObject` dentro de
  `raw/` e escrever logs no próprio log group (em vez da policy gerenciada
  `AWSLambdaBasicExecutionRole`, que libera qualquer log group da conta); o
  Scheduler só pode invocar essa Lambda específica, e só a partir desta conta.

## Estrutura do repositório

```
lambda/
  extract_bcb.py        # handler da Lambda: busca, valida e grava cada série
  data_quality.py       # regras de qualidade de dado
tests/                  # testes unitários (sem acessar internet nem AWS)
terraform/              # toda a infraestrutura
  build_layer.ps1/.sh   # gera a Lambda Layer com as dependências
.github/workflows/ci.yml
requirements.txt        # dependências da Lambda (vão para a layer)
requirements-dev.txt    # + pytest e ruff
```

## Deploy com Terraform

Pré-requisitos: [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.5,
Python 3 com `pip` e AWS CLI configurado (`aws configure`) com permissão para criar os
recursos (S3, Lambda, IAM, Glue, Athena, EventBridge Scheduler, CloudWatch, SNS).

```powershell
cd terraform

# 1. Variáveis: seu e-mail de alerta
copy terraform.tfvars.example terraform.tfvars   # depois edite o e-mail

# 2. Gerar a Lambda Layer (requests compilado para Linux)
powershell -ExecutionPolicy Bypass -File .\build_layer.ps1   # Windows
# ./build_layer.sh                                           # Linux/macOS

# 3. Criar a infraestrutura
terraform init
terraform plan
terraform apply
```

Depois do `apply`:

1. **Confirme a assinatura do SNS** no e-mail que chega da AWS — sem isso os alertas
   não são entregues.
2. **Rode a extração uma vez** para não esperar o agendamento:

   ```powershell
   aws lambda invoke --function-name extract-bcb-tf out.json
   type out.json
   ```

3. No console do **Athena**, selecione o workgroup `financial-data-tf` e o database
   `financial_data_tf`. Em *Saved queries* está pronta a consulta
   `ultimos-valores-por-serie`.

Para remover tudo: `terraform destroy`.

## Testes e CI

```bash
pip install -r requirements-dev.txt
pytest -v
ruff check . && ruff format --check .
```

Os testes substituem a API do Banco Central e o S3 por dublês, então rodam em
segundos, sem internet e sem credenciais. Cobrem montagem da URL e da janela de datas,
tratamento de erros HTTP, resposta `404` do SGS (sem dados no intervalo), o formato
JSON Lines gravado, o isolamento de falha entre séries e todas as regras de qualidade.

A cada push na `main` e em todo Pull Request, o **GitHub Actions** roda lint, testes,
`terraform fmt -check` e `terraform validate`.

## Limitações conhecidas

- **Duplicidade na camada raw**: como cada execução busca uma janela móvel (30 dias
  para Selic e dólar, 90 para IPCA), o mesmo ponto aparece em várias partições
  `data_execucao`. Por isso a consulta pronta filtra a execução mais recente. A
  solução definitiva é uma camada tratada (silver) deduplicada — tema do próximo
  projeto do portfólio (Lakehouse com PySpark).
- O alarme de "não rodou" pode disparar logo após o primeiro deploy, antes da
  primeira execução. Rodar a Lambda uma vez manualmente (passo 2 acima) evita isso.

## Troubleshooting — problemas reais encontrados e resolvidos

### 1. Coluna única `array` em vez de `data` e `valor` no schema

A API do Banco Central retorna um array JSON único (`[{...}, {...}, ...]`). Quando
salvo dessa forma no S3, o Glue Crawler não consegue "explodir" o array em colunas —
ele cria uma única coluna do tipo `array`, inutilizável em queries simples.

**Correção**: o código transforma a lista em **JSON Lines** antes de salvar (um
objeto JSON por linha, sem colchetes envolvendo tudo).

### 2. `Service is unable to assume provided role. Please verify role's TrustPolicy` (Fase 1)

Ao criar o Glue Crawler pelo wizard do console AWS (opção "Create default role"), a
criação da IAM Role falhava silenciosamente — a Role nunca chegava a existir.

**Causa raiz**: o usuário IAM usado não tinha permissão para criar Roles. Mesmo depois
de corrigir, o wizard continuou falhando nesse fluxo — contornado criando a Role
manualmente pelo console IAM e selecionando "Use another role" no Crawler. Na Fase 2
esse problema deixa de existir: as roles são declaradas em Terraform.

### 3. `ORDER BY data DESC` retornando ordem incorreta no Athena

A coluna `data` é texto (`dd/mm/yyyy`), então `ORDER BY` comparava como string —
`"31/07/2026"` era considerado "maior" que `"05/08/2026"`.

**Correção**: `date_parse(data, '%d/%m/%Y')` para converter em data real antes de
ordenar (usado na consulta pronta do Athena).

## Possíveis evoluções

- [x] Reescrever a infraestrutura como código (Terraform)
- [x] Automatizar a execução periódica com Amazon EventBridge Scheduler
- [x] Validação de qualidade de dado antes de gravar
- [x] CI no GitHub Actions (lint, testes, validação do Terraform)
- [x] Alertas de falha e de "não execução"
- [ ] Deploy contínuo (`terraform apply` pelo GitHub Actions com OIDC, sem chave de acesso)
- [ ] State remoto do Terraform (S3 + lock) para trabalhar de mais de uma máquina
- [ ] Camada silver deduplicada e em Parquet
- [ ] Mais séries econômicas (basta adicionar em `series`, no `terraform.tfvars`)

## Autor

Higor Cunha — Analista de TI Jr. em transição para Engenharia de Dados.
