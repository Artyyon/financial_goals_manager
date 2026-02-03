# 📦 Documentação de Versionamento com Docker Compose

**Projeto: Atlas Life**

---

## 1. Objetivo

Este documento descreve o padrão adotado para **versionar, construir e executar** o projeto **Atlas Life** utilizando **Docker Compose**, permitindo:

* Versionamento real do software
* Execução de múltiplas versões em paralelo
* Isolamento de ambientes
* Facilidade de rollback
* Base sólida para CI/CD

---

## 2. Conceito-chave

No Docker, **versionamento correto do software** deve ser feito por meio da **tag da imagem**, e não apenas pelo nome do container ou do projeto.

> 🔑 **Regra de ouro**
>
> * Nome do projeto (`-p`) → isolamento de ambiente
> * Tag da imagem (`image:app:1.01`) → versão do software

---

## 3. Estrutura de arquivos

```text
atlas-life/
├── docker-compose.yml
├── .env
├── Dockerfile
├── db/
│   └── Production/
└── key/
```

---

## 4. Arquivo `.env`

O arquivo `.env` centraliza as variáveis de configuração do projeto.

```env
APP_NAME=atlas-life
APP_VERSION=1.01
APP_PORT=8501
```

### Descrição das variáveis

| Variável      | Descrição              |
| ------------- | ---------------------- |
| `APP_NAME`    | Nome lógico do projeto |
| `APP_VERSION` | Versão do software     |
| `APP_PORT`    | Porta exposta no host  |

---

## 5. Arquivo `docker-compose.yml`

```yaml
services:
  atlas-life:
    image: ${APP_NAME}:${APP_VERSION}
    build:
      context: .
    container_name: ${APP_NAME}_${APP_VERSION}
    ports:
      - "${APP_PORT}:8501"
    volumes:
      - ./db/Production:/app/db/Production
      - ./key:/app/key:ro
    env_file:
      - .env
    restart: unless-stopped
```

---

## 6. Explicação técnica (passo a passo)

### 6.1 Versionamento da imagem

```yaml
image: ${APP_NAME}:${APP_VERSION}
```

Define a imagem Docker com **tag de versão**.

📦 Exemplo gerado:

```text
atlas-life:1.01
```

Isso permite:

* Identificar exatamente qual código está rodando
* Fazer rollback para versões anteriores
* Publicar imagens versionadas em registry (Docker Hub, GHCR etc.)

---

### 6.2 Nome do container

```yaml
container_name: ${APP_NAME}_${APP_VERSION}
```

Facilita:

* Debug
* Monitoramento
* Logs
* Identificação rápida no `docker ps`

---

### 6.3 Porta parametrizada

```yaml
ports:
  - "${APP_PORT}:8501"
```

Permite executar **múltiplas versões simultaneamente**:

| Versão | Porta |
| ------ | ----- |
| 1.01   | 8501  |
| 1.02   | 8502  |

---

### 6.4 Volumes persistentes

```yaml
volumes:
  - ./db/Production:/app/db/Production
  - ./key:/app/key:ro
```

* `db/Production` → persistência de dados
* `key` → volume somente leitura (segurança)

---

### 6.5 Política de reinício

```yaml
restart: unless-stopped
```

O container:

* Reinicia automaticamente em falhas
* Não reinicia se for parado manualmente

---

## 7. Subindo o projeto

### 7.1 Subida padrão

```bash
docker compose up -d --build
```

O Docker Compose carrega automaticamente o `.env`.

---

### 7.2 Subida com isolamento explícito

```bash
docker compose -p atlas_life_v1_01 up -d --build
```

Isso cria:

* Containers
* Network
* Volumes

todos isolados sob o mesmo projeto.

---

## 8. Executando múltiplas versões

### Exemplo: versão 1.02

```env
APP_VERSION=1.02
APP_PORT=8502
```

```bash
docker compose -p atlas_life_v1_02 up -d --build
```

Resultado:

```text
atlas-life:1.02
atlas-life_1.02
```

✔️ Ambas versões podem rodar em paralelo.

---

## 9. Rollback

Para voltar para uma versão anterior:

```env
APP_VERSION=1.01
APP_PORT=8501
```

```bash
docker compose up -d
```

✔️ Sem rebuild se a imagem já existir
✔️ Sem impacto em outras versões

---

## 10. Boas práticas adotadas

* Versionamento semântico via tag de imagem
* Configuração centralizada no `.env`
* Containers com nomes legíveis
* Volumes persistentes e seguros
* Compatível com CI/CD

---

## 11. Próximos passos (opcional)

Este padrão está pronto para:

* GitHub Actions
* Docker Hub / GHCR
* `docker-compose.prod.yml`
* Makefile (`make up VERSION=1.02`)
* Blue-Green deployment

---

## 12. Conclusão

Este modelo garante que:

✔️ A versão do software seja clara
✔️ Ambientes sejam isolados
✔️ O deploy seja previsível
✔️ O rollback seja trivial