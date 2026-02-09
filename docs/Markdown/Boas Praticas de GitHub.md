# 📘 Git Workflow, Branches, Releases e Versionamento

## Objetivo

Este documento define o fluxo de trabalho com **Git** para:

* Desenvolver com segurança (sem quebrar o que você usa)
* Separar ambientes (`dev`, `beta`, `prod`)
* Gerar releases versionados (`vMAJOR.MINOR.PATCH-status`)
* Rastrear mudanças com histórico claro (commits, tags e changelog)

---

# 1. Convenções básicas

## 1.1. Nome do repositório e branch principal

Recomendação:

* `main` → produção (o que você confia / release estável)
* `beta` → versão de uso real (produção pessoal)
* `dev` → desenvolvimento ativo (instável)

> Se você já usa `master`, mantenha ou migre para `main`. O importante é ser consistente.

---

# 2. Branches e propósito

## 2.1. Branch `dev`

**Finalidade:** desenvolvimento ativo e instável.

* Aqui entram novas features, refactors, experimentos
* Pode quebrar
* Pode ter migrações incompletas
* Usa banco de dados de teste

Versões típicas:

* `0.x.y-dev`
* `0.x.y-alpha`

---

## 2.2. Branch `beta`

**Finalidade:** versão utilizável com **dados reais** (produção pessoal).

* Atualiza só quando `dev` estiver minimamente confiável
* Mudanças são controladas
* Backups são obrigatórios antes de atualizar
* Migrações devem ser testadas antes de aplicar

Versões típicas:

* `0.x.y-beta`

---

## 2.3. Branch `main`

**Finalidade:** produção oficial (estável).

* Recebe apenas código validado
* Releases finais (sem sufixo): `1.0.0`, `1.1.0`, etc.
* Ideal para publicação / distribuição

Versões típicas:

* `1.x.y`

---

# 3. Estrutura de branches recomendada

```
main  (prod / stable)
  ↑
beta  (uso real com dados)
  ↑
dev   (desenvolvimento)
```

**Fluxo:**

* Você trabalha no `dev`
* Promove para `beta` quando estiver usável
* Promove para `main` quando estiver estável

---

# 4. Feature branches (opcional, mas recomendado)

Para organizar melhor, crie branches temporárias a partir de `dev`:

Padrão de nome:

```
feat/<nome-curto>
fix/<nome-curto>
refactor/<nome-curto>
chore/<nome-curto>
```

Exemplos:

* `feat/relatorios-mensais`
* `fix/correcao-saldo-negativo`
* `refactor/repositorio-dados`
* `chore/atualiza-dependencias`

---

# 5. Regras de commit

## 5.1. Commits pequenos e objetivos

Cada commit deve:

* fazer uma coisa bem definida
* compilar/rodar (quando possível)
* ter mensagem clara

## 5.2. Conventional Commits (recomendado)

Formato:

```
tipo(escopo): mensagem
```

Tipos comuns:

* `feat:` nova funcionalidade
* `fix:` correção de bug
* `refactor:` refatoração (sem mudança de comportamento)
* `perf:` melhoria de performance
* `test:` testes
* `docs:` documentação
* `chore:` tarefas gerais (deps, configs)

Exemplos:

* `feat(finance): adicionar categoria de despesas`
* `fix(calc): corrigir arredondamento do saldo`
* `refactor(db): separar camada de acesso ao banco`
* `docs: atualizar guia de versionamento`

Referência: [https://www.conventionalcommits.org/pt-br/v1.0.0/](https://www.conventionalcommits.org/pt-br/v1.0.0/)

---

# 6. Versionamento no Git (tags)

## 6.1. Padrão de tag

Use o prefixo `v`:

```
vMAJOR.MINOR.PATCH[-status]
```

Exemplos:

* `v0.6.0-dev`
* `v0.5.0-beta`
* `v0.9.0-rc.1`
* `v1.0.0`

## 6.2. Criar tag

Tag anotada (recomendado):

```bash
git tag -a v0.5.0-beta -m "Release v0.5.0-beta"
git push origin v0.5.0-beta
```

Listar tags:

```bash
git tag
```

Ver detalhes:

```bash
git show v0.5.0-beta
```

---

# 7. Processo de release

## 7.1. Release para `beta` (uso real)

### Passo a passo

1. Garantir `dev` funcional
2. **Atualizar versão** (ex: `0.6.0-beta`)
3. Atualizar `CHANGELOG.md`
4. Merge `dev` → `beta`
5. Criar tag `v0.6.0-beta`
6. Fazer backup do banco beta
7. Aplicar migrações
8. Validar sistema rodando

### Comandos (exemplo)

```bash
git checkout beta
git pull

git merge dev
git push

git tag -a v0.6.0-beta -m "Release v0.6.0-beta"
git push origin v0.6.0-beta
```

---

## 7.2. Release para `main` (estável)

Quando o beta estiver sólido:

1. Atualizar versão para `1.0.0` (ou `1.x.y`)
2. Atualizar changelog
3. Merge `beta` → `main`
4. Criar tag `v1.0.0`
5. Publicar release (se fizer sentido)

```bash
git checkout main
git pull

git merge beta
git push

git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

---

# 8. Hotfix (correção urgente no beta/prod)

Se apareceu bug crítico no que você está usando:

## 8.1. Hotfix no `beta`

1. Criar branch a partir de `beta`

```bash
git checkout beta
git pull
git checkout -b fix/bug-critico
```

2. Corrigir e commitar

```bash
git commit -am "fix: corrigir bug crítico no cálculo"
```

3. Merge de volta para `beta`, tag e push

```bash
git checkout beta
git merge fix/bug-critico
git push

git tag -a v0.6.1-beta -m "Hotfix v0.6.1-beta"
git push origin v0.6.1-beta
```

4. Levar a correção para `dev` também (para não “perder” a correção)

```bash
git checkout dev
git merge beta
git push
```

---

# 9. Proteção por ser sistema financeiro

## 9.1. Regra de ouro

> Nunca aplique mudanças de `dev` no ambiente com dados reais sem testar.

## 9.2. Backups obrigatórios antes de atualizar `beta` ou `main`

Checklist mínimo:

* [ ] Backup do banco de dados
* [ ] Backup do arquivo `.env`/config
* [ ] Export opcional (CSV/JSON) dos dados críticos
* [ ] Teste de inicialização do sistema após update

---

# 10. `.gitignore` recomendado (para evitar vazar dados)

Exemplo (ajuste conforme seu stack):

```gitignore
# ambientes e segredos
.env
.env.*
*.key
*.pem

# bancos locais
*.db
*.sqlite
*.sqlite3

# logs
logs/
*.log

# cache
__pycache__/
*.pyc

# builds
dist/
build/
```

---

# 11. Modelo de release checklist

## Para promover `dev` → `beta`

* [ ] Rodou testes principais
* [ ] Aplicou migrações em banco de teste
* [ ] Atualizou `CHANGELOG.md`
* [ ] Atualizou número da versão no sistema
* [ ] Merge `dev` → `beta`
* [ ] Criou tag `vX.Y.Z-beta`
* [ ] Backup do banco real
* [ ] Migração aplicada no banco real
* [ ] Validou telas e cálculos críticos (saldo, entradas, saídas)

## Para promover `beta` → `main`

* [ ] Beta rodou um tempo sem bugs críticos
* [ ] Changelog revisado
* [ ] Versão final sem sufixo (`1.0.0`)
* [ ] Merge `beta` → `main`
* [ ] Tag `v1.0.0`

---

# 12. Comandos úteis do dia a dia

Ver status:

```bash
git status
```

Atualizar sua branch:

```bash
git pull
```

Criar branch:

```bash
git checkout -b feat/nova-feature
```

Trocar branch:

```bash
git checkout dev
```

Ver histórico:

```bash
git log --oneline --decorate --graph --all
```

---

# 13. Exemplo real (timeline)

* Você usa no dia a dia:

  * `beta` em `v0.5.0-beta`
* Você está desenvolvendo novidades:

  * `dev` em `0.6.0-dev`
* Quando as novidades ficarem seguras:

  * promove `dev` → `beta`
  * cria `v0.6.0-beta`

