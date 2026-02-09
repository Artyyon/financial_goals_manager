# 📘 Política de Versionamento e Ambientes

## Objetivo

Este documento define o padrão de versionamento do sistema, os níveis de estabilidade e a separação entre ambientes de desenvolvimento, testes e uso real.

O objetivo é:

* Garantir clareza sobre o estado do sistema
* Evitar perda de dados
* Permitir evolução controlada
* Manter histórico organizado das mudanças

---

# 1. Padrão de Versionamento

O sistema segue o padrão **Versionamento Semântico (Semantic Versioning)**:

```
MAJOR.MINOR.PATCH[-status]
```

Referência oficial:
[https://semver.org/lang/pt-BR/](https://semver.org/lang/pt-BR/)

## Estrutura

| Parte  | Significado                           |
| ------ | ------------------------------------- |
| MAJOR  | Mudanças grandes ou incompatíveis     |
| MINOR  | Novas funcionalidades compatíveis     |
| PATCH  | Correções de bugs ou ajustes pequenos |
| status | Indica nível de estabilidade          |

### Exemplos

```
0.1.0-dev
0.5.0-beta
0.9.0-rc
1.0.0
1.1.2
```

---

# 2. Significado das Versões

## Versões abaixo de 1.0.0

```
0.x.x = sistema ainda em evolução
```

Características:

* Estrutura pode mudar
* Funcionalidades incompletas
* Possíveis instabilidades

## Versão 1.0.0

Indica:

* Sistema funcional e confiável
* Estrutura principal estabilizada
* Pronto para uso em produção

---

# 3. Status de Estabilidade

Os sufixos indicam o nível de maturidade da versão.

## dev

```
0.6.0-dev
```

Uso:

* Desenvolvimento ativo
* Testes de novas funcionalidades
* Pode quebrar ou perder dados

Características:

* Instável
* Mudanças frequentes
* Não usar com dados reais

---

## alpha

```
0.3.0-alpha
```

Uso:

* Protótipos
* Funcionalidades iniciais
* Testes internos

---

## beta

```
0.5.0-beta
```

Uso:

* Sistema utilizável
* Pode conter bugs
* Dados reais permitidos (com backup)

Características:

* Funcionalidade principal já existe
* Mudanças controladas
* Ambiente de uso real (produção pessoal)

---

## rc (Release Candidate)

```
0.9.0-rc
```

Uso:

* Versão candidata à final
* Apenas correções críticas

---

## stable (sem sufixo)

```
1.0.0
```

Uso:

* Produção oficial
* Sistema confiável

---

# 4. Quando Incrementar a Versão

## PATCH (x.x.1)

Quando:

* Correção de bugs
* Ajustes pequenos
* Refatorações sem mudança de comportamento

Exemplo:

```
0.5.0-beta → 0.5.1-beta
```

---

## MINOR (x.1.0)

Quando:

* Nova funcionalidade
* Nova tela ou módulo
* Melhoria relevante

Exemplo:

```
0.5.0-beta → 0.6.0-dev
```

---

## MAJOR (1.0.0)

Quando:

* Mudanças incompatíveis
* Alteração estrutural grande
* Mudança de arquitetura ou banco

Exemplo:

```
0.9.0 → 1.0.0
```

---

# 5. Separação de Ambientes

Além da versão, o sistema deve ter **ambientes separados**.

| Ambiente | Finalidade           |
| -------- | -------------------- |
| dev      | desenvolvimento      |
| beta     | uso real com cautela |
| prod     | produção oficial     |

## Variável de ambiente

```
ENV=dev
ENV=beta
ENV=prod
```

---

# 6. Bancos de Dados por Ambiente

Nunca misturar dados entre ambientes.

Exemplo:

```
finance_dev.db
finance_beta.db
finance_prod.db
```

Regras:

### dev

* Pode ser apagado
* Dados fictícios

### beta

* Dados reais
* Backup obrigatório

### prod

* Uso definitivo
* Máxima estabilidade

---

# 7. Fluxo de Desenvolvimento

Fluxo recomendado:

### Passo 1 — Desenvolvimento

```
0.6.0-dev
```

Testar novas funcionalidades.

---

### Passo 2 — Teste em uso real

Quando estiver utilizável:

```
0.6.0-beta
```

Usar no dia a dia.

---

### Passo 3 — Estabilização

Após confiança:

```
1.0.0
```

---

# 8. Fluxo de Atualização (Importante para dados financeiros)

Sempre seguir:

```
1. Backup do banco beta/prod
2. Atualizar o sistema
3. Executar migrações
4. Validar funcionamento
```

Nunca atualizar sem backup.

---

# 9. Versionamento com Git

Tags recomendadas:

```
git tag v0.5.0-beta
git tag v1.0.0
```

Listar versões:

```
git tag
```

---

# 10. CHANGELOG

Manter histórico das mudanças.

Arquivo:

```
CHANGELOG.md
```

Modelo:

```markdown
## 0.6.0-beta
- Adicionado módulo de relatórios
- Melhorada validação de entradas

## 0.5.1-beta
- Correção de erro no cálculo de saldo

## 0.5.0-beta
- Primeira versão utilizável
```

Referência:
[https://keepachangelog.com/pt-BR/1.0.0/](https://keepachangelog.com/pt-BR/1.0.0/)

---

# 11. Regra Prática (Resumo)

| Situação               | Versão     |
| ---------------------- | ---------- |
| Testando código novo   | x.x.x-dev  |
| Usando com dados reais | x.x.x-beta |
| Quase estável          | x.x.x-rc   |
| Confiável              | 1.x.x      |

---

# 12. Exemplo de Evolução do Sistema Financeiro

```
0.1.0-alpha   Estrutura inicial
0.3.0-alpha   Cadastro de despesas
0.5.0-beta    Uso real pessoal
0.6.0-dev     Novas funcionalidades em teste
0.6.0-beta    Versão atualizada para uso
0.9.0-rc      Estabilização
1.0.0         Primeira versão oficial
```

---

# 13. Boas Práticas

* Nunca usar versão 1.x antes da estabilidade real
* Sempre separar ambientes
* Nunca atualizar banco real sem backup
* Versionar cada release no Git
* Manter CHANGELOG atualizado
