# 🏡 LuxHome Imóveis — Sistema de Gestão e Vitrine Imobiliária

Sistema web profissional desenvolvido em **Python (Flask)** e **MongoDB Atlas**, projetado para imobiliárias de alto padrão. O projeto conta com controle de acesso baseado em papéis (RBAC), separação de dados públicos e privados, upload inteligente de mídias e gestão ágil de portfólio.

---

## 🚀 Tecnologias Utilizadas

* **Backend:** Python 3.10+, Flask, Flask-PyMongo, Werkzeug
* **Banco de Dados:** MongoDB Atlas (NoSQL)
* **Segurança:** Bcrypt (hashing de senhas), Sessões criptografadas e Decorators de permissão
* **Frontend / UI:** Tailwind CSS (via CDN) para design responsivo e moderno
* **Gerenciamento de Mídia:** Sistema de pastas dinâmicas locais (`static/upload/`)

---

## ✨ Funcionalidades Principais

1. **Vitrine Pública Dinâmica:**
   * Exibição em tempo real dos imóveis ativos cadastrados no banco de dados.
   * Sistema de destaque (`True` / `False`) para priorizar imóveis na página inicial.
2. **Painel Administrativo (Admin):**
   * **Geração Automática de Código:** Sequenciamento inteligente (ex: `AP0001`, `AP0002`).
   * **Upload Inteligente de Imagens:** Criação automática de diretórios por código de imóvel e renomeação padronizada de arquivos.
   * **Soft Delete (Exclusão Lógica):** Os imóveis são desativados (`status: "inativo"`) para preservar o histórico e relatórios internos, sumindo apenas da vitrine pública.
   * **Gestão de Usuários e Permissões:** Cadastro de novos administradores, corretores e clientes.
3. **Segurança e Privacidade de Dados:**
   * Estrutura de banco de dados desacoplada (`imoveis` para dados públicos e `imoveis_enderecos` para informações sensíveis de localização, acessíveis apenas por usuários autenticados).

---

## 🛠️ Como Executar o Projeto Localmente

Siga os passos abaixo para rodar o projeto na sua máquina:

### 1. Clonar o Repositório
```bash
git clone [https://github.com/seu-usuario/luxhome-imoveis.git](https://github.com/seu-usuario/luxhome-imoveis.git)
cd luxhome-imoveis