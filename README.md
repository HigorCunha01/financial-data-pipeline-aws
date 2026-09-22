# 💰 Pipeline Serverless de Dados Financeiros — AWS

Pipeline de dados serverless que extrai indicadores econômicos (Selic, IPCA e câmbio)
da API pública do Banco Central do Brasil, e disponibiliza os dados para consulta via
SQL, sem nenhum banco de dados tradicional rodando — usando S3, Glue e Athena.

Projeto construído do zero, com apoio de mentoria guiada, como parte da minha
transição para Engenharia de Dados, aplicando Python e os principais serviços de
dados da AWS em uma arquitetura completa de ponta a ponta.

## Arquitetura

```
                 ┌──────────────────────────┐
                 │  API do Banco Central     │  (SGS — séries temporais, sem API key)
                 │  (Selic, IPCA, Dólar)     │
                 └────────────┬──────────────┘
                              │  requests (Python, dentro da AWS Lambda)
                              ▼
                 ┌──────────────────────────┐
                 │  Amazon S3                │  raw/serie=<nome>/data_execucao=<data>/
                 │  (JSON Lines particionado)│  dados.json
                 └────────────┬──────────────┘
                              │  AWS Glue Crawler
                              ▼
                 ┌──────────────────────────┐
                 │  Glue Data Catalog        │  database: financial_data
                 │  (schema inferido)        │  tabela: raw
                 └────────────┬──────────────┘
                              │  SQL
                              ▼
                 ┌──────────────────────────┐
                 │  Amazon Athena             │  consultas SQL direto sobre o S3
                 └──────────────────────────┘

Orquestração planejada: Amazon EventBridge Scheduler → Lambda (execução diária)
```

## Stack

| Camada           | Ferramenta                                  |
|------------------|-----------------------------------------------|
| Extração         | Python (`requests`, `boto3`) rodando em AWS Lambda |
| Empacotamento    | AWS Lambda Layers (dependência `requests` separada do código) |
| Armazenamento    | Amazon S3 (particionado, formato JSON Lines) |
| Catalogação      | AWS Glue (Crawler + Data Catalog)            |
| Consulta         | Amazon Athena (SQL sobre S3, sem banco tradicional) |
| Permissões       | IAM (roles e policies por serviço, menor privilégio) |

## Por que essas escolhas

- **Serverless em vez de servidor fixo**: nenhuma infraestrutura fica ligada 24h —
  o Lambda só executa quando disparado, e o Athena só "existe" na hora da query.
  Toda a stack usada aqui está dentro da camada gratuita da AWS (Always Free / S3 e Lambda).
- **Particionamento por série e data** (`serie=selic/data_execucao=2026-08-27/`):
  reduz o volume de dado escaneado a cada consulta no Athena — que cobra por dado
  escaneado, então particionamento mal pensado é literalmente dinheiro jogado fora
  em produção.
- **JSON Lines em vez de array JSON**: formato em que cada linha do arquivo é um
  registro independente, permitindo que o Glue Crawler infira colunas reais
  (`data`, `valor`) em vez de uma única coluna do tipo `array` (ver Troubleshooting).
- **Lambda Layer para a dependência `requests`**: separa "código de negócio" de
  "biblioteca de terceiro", permitindo reaproveitar a mesma layer em futuras funções
  Lambda sem reempacotar nada.
- **IAM com Roles específicas por serviço**: cada serviço (Lambda, Glue) tem sua
  própria Role, seguindo o princípio do menor privilégio — nenhuma credencial de
  usuário é usada em tempo de execução.

## Como funciona (fluxo de execução)

1. A função Lambda (`extract_bcb.py`) é executada, buscando os últimos 30 dias de
   3 séries do Banco Central (Selic, IPCA, Dólar).
2. Cada série é salva como um arquivo `dados.json` no S3, em formato JSON Lines,
   dentro de um caminho particionado por série e data de execução.
3. O AWS Glue Crawler varre o bucket, infere o schema automaticamente e popula o
   Glue Data Catalog (database `financial_data`, tabela `raw`).
4. Consultas SQL são feitas diretamente no Amazon Athena, sem necessidade de
   carregar os dados em nenhum banco de dados.

## Reproduzindo a Lambda Layer localmente

A pasta `lambda_layer/` (com as dependências instaladas) não é versionada — ela é
100% reproduzível a partir do `requirements.txt`:

```bash
mkdir -p lambda_layer/python
pip install requests -t lambda_layer/python
cd lambda_layer
zip -r requests-layer.zip python
```

O `.zip` gerado é o que deve ser enviado como uma nova versão da Lambda Layer no
console AWS (Lambda → Layers → Create layer), com runtime compatível com Python 3.x.

## Deploy (manual, via console AWS)

Este projeto foi implantado manualmente pelo console da AWS, como parte do
aprendizado da plataforma. Os passos gerais:

1. Criar um bucket S3 para os dados brutos.
2. Criar a função Lambda (`extract_bcb.py`), anexando a Lambda Layer com `requests`.
3. Configurar a execution role da Lambda com permissão de escrita no bucket S3.
4. Criar um AWS Glue Crawler apontando para o caminho `s3://<bucket>/raw/`,
   com uma IAM Role própria (permissão de leitura no S3 + escrita no Glue Catalog).
5. Rodar o Crawler e consultar os dados no Amazon Athena.

> Próxima evolução planejada: reescrever esse deploy como Infrastructure as Code
> (Terraform), e automatizar a execução periódica com Amazon EventBridge Scheduler.

## Troubleshooting — problemas reais encontrados e resolvidos

### 1. Coluna única `array` em vez de `data` e `valor` no schema

A API do Banco Central retorna um array JSON único (`[{...}, {...}, ...]`). Quando
salvo dessa forma no S3, o Glue Crawler não consegue "explodir" o array em colunas —
ele cria uma única coluna do tipo `array`, inutilizável em queries simples.

**Correção**: o código transforma a lista em **JSON Lines** antes de salvar (um
objeto JSON por linha, sem colchetes envolvendo tudo). O Glue Crawler então infere
corretamente as colunas `data` e `valor`.

### 2. `dbt1005` / `Service is unable to assume provided role. Please verify role's TrustPolicy`

Ao criar o Glue Crawler pelo próprio wizard do console AWS (opção "Create default
role"), a criação da IAM Role falhava silenciosamente — a Role nunca chegava a
existir de fato, mesmo sem erro aparente na hora da criação.

**Causa raiz**: o usuário IAM usado não tinha permissão para criar Roles (`IAMFullAccess`
ausente). Mesmo depois de corrigir essa permissão, o wizard do Glue continuou
falhando nesse fluxo específico — contornado criando a Role manualmente pelo
console IAM (Serviço confiável: Glue, política `AWSGlueServiceRole` +
`AmazonS3ReadOnlyAccess`) e selecionando "Use another role" na tela do Crawler.

### 3. `ORDER BY data DESC` retornando ordem incorreta no Athena

A coluna `data` é armazenada como texto (`dd/mm/yyyy`), então `ORDER BY` comparava
os valores como string (ordenação lexicográfica), não como data real — por exemplo,
`"31/07/2026"` era considerado "maior" que `"05/08/2026"`.

**Correção**: uso da função `date_parse(data, '%d/%m/%Y')` dentro do `ORDER BY`,
convertendo o texto para um tipo `date` real antes de ordenar.

## Possíveis evoluções

- [ ] Reescrever a infraestrutura como código (Terraform), em vez de configuração manual via console
- [ ] Automatizar a execução periódica com Amazon EventBridge Scheduler
- [ ] Adicionar testes de qualidade de dado (ex: Great Expectations) antes da catalogação
- [ ] Pipeline de CI/CD (GitHub Actions) para validar e empacotar a função Lambda automaticamente
- [ ] Adicionar mais séries econômicas (basta editar o dicionário `SERIES` em `extract_bcb.py`)

## Autor

Higor Cunha — Analista de TI Jr. em transição para Engenharia de Dados.
