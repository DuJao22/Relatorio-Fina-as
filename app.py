from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime, timedelta
import locale
from functools import wraps
import json

app = Flask(__name__)
app.secret_key = 'chave_secreta_clinica_medica_2024'

# Configurar locale para formatação brasileira
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_ALL, 'pt_BR')
    except:
        pass

def init_db():
    """Inicializa o banco de dados com as tabelas necessárias"""
    conn = sqlite3.connect('clinica.db')
    cursor = conn.cursor()
    
    # Tabela pessoas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pessoas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('Médico', 'Funcionário')),
            pix TEXT,
            salario REAL DEFAULT 0,
            passagem_padrao REAL DEFAULT 0,
            data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela vales
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            valor REAL NOT NULL,
            pessoa_id INTEGER,
            data DATE NOT NULL,
            clinica TEXT NOT NULL CHECK (clinica IN ('Belo Horizonte', 'Contagem')),
            FOREIGN KEY (pessoa_id) REFERENCES pessoas (id)
        )
    ''')
    
    # Tabela despesas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS despesas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            valor REAL NOT NULL,
            descricao TEXT NOT NULL,
            data DATE NOT NULL,
            clinica TEXT NOT NULL CHECK (clinica IN ('Belo Horizonte', 'Contagem'))
        )
    ''')
    
    # Tabela pagamentos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pagamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pessoa_id INTEGER,
            valor_base REAL NOT NULL,
            passagem REAL DEFAULT 0,
            vale REAL DEFAULT 0,
            total_final REAL NOT NULL,
            clinica TEXT NOT NULL CHECK (clinica IN ('Belo Horizonte', 'Contagem')),
            data DATE NOT NULL,
            FOREIGN KEY (pessoa_id) REFERENCES pessoas (id)
        )
    ''')
    
    # Tabela faturamentos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS faturamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            valor REAL NOT NULL,
            convenio TEXT NOT NULL,
            data DATE NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

def formatar_moeda(valor):
    """Formata valor para moeda brasileira"""
    if valor is None:
        valor = 0
    try:
        return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except:
        return f"R$ 0,00"

def get_db_connection():
    """Retorna conexão com o banco de dados"""
    conn = sqlite3.connect('clinica.db')
    conn.row_factory = sqlite3.Row
    return conn

def identificar_clinica_pessoa(pessoa_id):
    """Identifica a clínica de origem de uma pessoa"""
    conn = get_db_connection()
    
    # Verificar em vales
    vales_bh = conn.execute(
        'SELECT COUNT(*) as count FROM vales WHERE pessoa_id = ? AND clinica = "Belo Horizonte"',
        (pessoa_id,)
    ).fetchone()['count']
    
    vales_contagem = conn.execute(
        'SELECT COUNT(*) as count FROM vales WHERE pessoa_id = ? AND clinica = "Contagem"',
        (pessoa_id,)
    ).fetchone()['count']
    
    # Verificar em pagamentos
    pag_bh = conn.execute(
        'SELECT COUNT(*) as count FROM pagamentos WHERE pessoa_id = ? AND clinica = "Belo Horizonte"',
        (pessoa_id,)
    ).fetchone()['count']
    
    pag_contagem = conn.execute(
        'SELECT COUNT(*) as count FROM pagamentos WHERE pessoa_id = ? AND clinica = "Contagem"',
        (pessoa_id,)
    ).fetchone()['count']
    
    conn.close()
    
    total_bh = vales_bh + pag_bh
    total_contagem = vales_contagem + pag_contagem
    
    if total_bh > 0 and total_contagem > 0:
        return "Ambas"
    elif total_bh > 0:
        return "Clínica BH"
    elif total_contagem > 0:
        return "Clínica Contagem"
    else:
        return "Não definida"

@app.template_filter('money')
def money_filter(value):
    return formatar_moeda(value)

@app.context_processor
def inject_globals():
    return {
        'formatar_moeda': formatar_moeda,
        'datetime': datetime
    }

@app.route('/')
def index():
    clinica_selecionada = request.args.get('clinica', 'bh')
    nome_clinica = "Belo Horizonte" if clinica_selecionada == 'bh' else "Contagem"
    
    mes = request.args.get('mes')
    if not mes:
        mes = datetime.now().strftime('%Y-%m')
    
    conn = get_db_connection()
    
    # Estatísticas do mês
    if clinica_selecionada == 'bh':
        clinica_filtro = 'Belo Horizonte'
    else:
        clinica_filtro = 'Contagem'
    
    # Faturamento total (não filtrado por clínica)
    faturamento = conn.execute(
        'SELECT COALESCE(SUM(valor), 0) as total FROM faturamentos WHERE strftime("%Y-%m", data) = ?',
        (mes,)
    ).fetchone()['total']
    
    # Despesas da clínica
    despesas = conn.execute(
        'SELECT COALESCE(SUM(valor), 0) as total FROM despesas WHERE clinica = ? AND strftime("%Y-%m", data) = ?',
        (clinica_filtro, mes)
    ).fetchone()['total']
    
    # Pagamentos da clínica
    pagamentos = conn.execute(
        'SELECT COALESCE(SUM(total_final), 0) as total FROM pagamentos WHERE clinica = ? AND strftime("%Y-%m", data) = ?',
        (clinica_filtro, mes)
    ).fetchone()['total']
    
    # Funcionários ativos da clínica
    funcionarios = conn.execute(
        '''SELECT COUNT(DISTINCT p.id) as total 
           FROM pessoas p 
           JOIN pagamentos pg ON p.id = pg.pessoa_id 
           WHERE pg.clinica = ? AND strftime("%Y-%m", pg.data) = ?''',
        (clinica_filtro, mes)
    ).fetchone()['total']
    
    lucro = faturamento - despesas - pagamentos
    
    # Dados para gráfico dos últimos 6 meses
    grafico_meses = []
    grafico_faturamento = []
    grafico_despesas = []
    
    for i in range(5, -1, -1):
        data_mes = datetime.now() - timedelta(days=30*i)
        mes_str = data_mes.strftime('%Y-%m')
        mes_nome = data_mes.strftime('%m/%Y')
        
        fat_mes = conn.execute(
            'SELECT COALESCE(SUM(valor), 0) as total FROM faturamentos WHERE strftime("%Y-%m", data) = ?',
            (mes_str,)
        ).fetchone()['total']
        
        desp_mes = conn.execute(
            'SELECT COALESCE(SUM(valor), 0) as total FROM despesas WHERE clinica = ? AND strftime("%Y-%m", data) = ?',
            (clinica_filtro, mes_str)
        ).fetchone()['total']
        
        grafico_meses.append(mes_nome)
        grafico_faturamento.append(fat_mes)
        grafico_despesas.append(desp_mes)
    
    conn.close()
    
    # Calcular alturas das barras para o gráfico
    max_valor = max(max(grafico_faturamento + grafico_despesas, default=1), 1)
    faturamento_heights = [(val / max_valor) * 100 for val in grafico_faturamento]
    despesas_heights = [(val / max_valor) * 100 for val in grafico_despesas]
    
    return render_template('index.html',
                         clinica=clinica_selecionada,
                         nome_clinica=nome_clinica,
                         mes=mes,
                         faturamento=faturamento,
                         despesas=despesas,
                         lucro=lucro,
                         funcionarios=funcionarios,
                         grafico_meses=grafico_meses,
                         grafico_faturamento=grafico_faturamento,
                         grafico_despesas=grafico_despesas,
                         faturamento_heights=faturamento_heights,
                         despesas_heights=despesas_heights)

@app.route('/pessoas')
def pessoas():
    clinica = request.args.get('clinica', 'bh')
    conn = get_db_connection()
    pessoas_list = conn.execute('SELECT * FROM pessoas ORDER BY tipo, nome').fetchall()
    conn.close()
    
    # Adicionar informação da clínica para cada pessoa
    pessoas_com_clinica = []
    for pessoa in pessoas_list:
        clinica_origem = "Ambas" if pessoa['tipo'] == 'Médico' else identificar_clinica_pessoa(pessoa['id'])
        pessoas_com_clinica.append({
            'id': pessoa['id'],
            'nome': pessoa['nome'],
            'tipo': pessoa['tipo'],
            'pix': pessoa['pix'],
            'salario': pessoa['salario'],
            'passagem_padrao': pessoa['passagem_padrao'],
            'clinica_origem': clinica_origem
        })
    
    return render_template('pessoas.html', pessoas=pessoas_com_clinica, clinica=clinica)

@app.route('/pessoas/adicionar', methods=['POST'])
def adicionar_pessoa():
    nome = request.form['nome']
    tipo = request.form['tipo']
    pix = request.form['pix']
    salario = float(request.form['salario']) if request.form['salario'] else 0
    passagem = float(request.form['passagem_padrao']) if request.form['passagem_padrao'] else 0
    
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO pessoas (nome, tipo, pix, salario, passagem_padrao) VALUES (?, ?, ?, ?, ?)',
        (nome, tipo, pix, salario, passagem)
    )
    conn.commit()
    conn.close()
    
    flash('Pessoa adicionada com sucesso!', 'success')
    return redirect(url_for('pessoas'))

@app.route('/pessoas/editar/<int:id>', methods=['POST'])
def editar_pessoa(id):
    nome = request.form['nome']
    tipo = request.form['tipo']
    pix = request.form['pix']
    salario = float(request.form['salario']) if request.form['salario'] else 0
    passagem = float(request.form['passagem_padrao']) if request.form['passagem_padrao'] else 0
    
    conn = get_db_connection()
    conn.execute(
        'UPDATE pessoas SET nome=?, tipo=?, pix=?, salario=?, passagem_padrao=? WHERE id=?',
        (nome, tipo, pix, salario, passagem, id)
    )
    conn.commit()
    conn.close()
    
    flash('Pessoa editada com sucesso!', 'success')
    return redirect(url_for('pessoas'))

@app.route('/pessoas/excluir/<int:id>')
def excluir_pessoa(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM pessoas WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    flash('Pessoa excluída com sucesso!', 'success')
    return redirect(url_for('pessoas'))

@app.route('/vales')
def vales():
    clinica = request.args.get('clinica', 'bh')
    nome_clinica = "Belo Horizonte" if clinica == 'bh' else "Contagem"
    
    conn = get_db_connection()
    vales_list = conn.execute(
        '''SELECT v.*, p.nome as pessoa_nome 
           FROM vales v 
           LEFT JOIN pessoas p ON v.pessoa_id = p.id 
           WHERE v.clinica = ? 
           ORDER BY v.data DESC''',
        (nome_clinica,)
    ).fetchall()
    
    pessoas_list = conn.execute('SELECT * FROM pessoas ORDER BY nome').fetchall()
    conn.close()
    
    return render_template('vales.html', vales=vales_list, pessoas=pessoas_list, clinica=clinica, nome_clinica=nome_clinica)

@app.route('/vales/adicionar', methods=['POST'])
def adicionar_vale():
    valor = float(request.form['valor'])
    pessoa_id = int(request.form['pessoa_id'])
    data = request.form['data']
    clinica_param = request.form['clinica']
    clinica_nome = "Belo Horizonte" if clinica_param == 'bh' else "Contagem"
    
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO vales (valor, pessoa_id, data, clinica) VALUES (?, ?, ?, ?)',
        (valor, pessoa_id, data, clinica_nome)
    )
    conn.commit()
    conn.close()
    
    flash('Vale adicionado com sucesso!', 'success')
    return redirect(url_for('vales', clinica=clinica_param))

@app.route('/vales/editar/<int:id>', methods=['POST'])
def editar_vale(id):
    valor = float(request.form['valor'])
    pessoa_id = int(request.form['pessoa_id'])
    data = request.form['data']
    clinica_param = request.form['clinica']
    clinica_nome = "Belo Horizonte" if clinica_param == 'bh' else "Contagem"
    
    conn = get_db_connection()
    conn.execute(
        'UPDATE vales SET valor=?, pessoa_id=?, data=?, clinica=? WHERE id=?',
        (valor, pessoa_id, data, clinica_nome, id)
    )
    conn.commit()
    conn.close()
    
    flash('Vale editado com sucesso!', 'success')
    return redirect(url_for('vales', clinica=clinica_param))

@app.route('/vales/excluir/<int:id>')
def excluir_vale(id):
    clinica = request.args.get('clinica', 'bh')
    conn = get_db_connection()
    conn.execute('DELETE FROM vales WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    flash('Vale excluído com sucesso!', 'success')
    return redirect(url_for('vales', clinica=clinica))

@app.route('/despesas')
def despesas():
    clinica = request.args.get('clinica', 'bh')
    nome_clinica = "Belo Horizonte" if clinica == 'bh' else "Contagem"
    
    conn = get_db_connection()
    despesas_list = conn.execute(
        'SELECT * FROM despesas WHERE clinica = ? ORDER BY data DESC',
        (nome_clinica,)
    ).fetchall()
    conn.close()
    
    return render_template('despesas.html', despesas=despesas_list, clinica=clinica, nome_clinica=nome_clinica)

@app.route('/despesas/adicionar', methods=['POST'])
def adicionar_despesa():
    valor = float(request.form['valor'])
    descricao = request.form['descricao']
    data = request.form['data']
    clinica_param = request.form['clinica']
    clinica_nome = "Belo Horizonte" if clinica_param == 'bh' else "Contagem"
    
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO despesas (valor, descricao, data, clinica) VALUES (?, ?, ?, ?)',
        (valor, descricao, data, clinica_nome)
    )
    conn.commit()
    conn.close()
    
    flash('Despesa adicionada com sucesso!', 'success')
    return redirect(url_for('despesas', clinica=clinica_param))

@app.route('/despesas/editar/<int:id>', methods=['POST'])
def editar_despesa(id):
    valor = float(request.form['valor'])
    descricao = request.form['descricao']
    data = request.form['data']
    clinica_param = request.form['clinica']
    clinica_nome = "Belo Horizonte" if clinica_param == 'bh' else "Contagem"
    
    conn = get_db_connection()
    conn.execute(
        'UPDATE despesas SET valor=?, descricao=?, data=?, clinica=? WHERE id=?',
        (valor, descricao, data, clinica_nome, id)
    )
    conn.commit()
    conn.close()
    
    flash('Despesa editada com sucesso!', 'success')
    return redirect(url_for('despesas', clinica=clinica_param))

@app.route('/despesas/excluir/<int:id>')
def excluir_despesa(id):
    clinica = request.args.get('clinica', 'bh')
    conn = get_db_connection()
    conn.execute('DELETE FROM despesas WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    flash('Despesa excluída com sucesso!', 'success')
    return redirect(url_for('despesas', clinica=clinica))

@app.route('/pagamentos')
def pagamentos():
    clinica = request.args.get('clinica', 'bh')
    nome_clinica = "Belo Horizonte" if clinica == 'bh' else "Contagem"
    
    conn = get_db_connection()
    pagamentos_list = conn.execute(
        '''SELECT p.*, pe.nome as pessoa_nome 
           FROM pagamentos p 
           LEFT JOIN pessoas pe ON p.pessoa_id = pe.id 
           WHERE p.clinica = ? 
           ORDER BY p.data DESC''',
        (nome_clinica,)
    ).fetchall()
    
    pessoas_list = conn.execute('SELECT * FROM pessoas ORDER BY nome').fetchall()
    conn.close()
    
    return render_template('pagamentos.html', pagamentos=pagamentos_list, pessoas=pessoas_list, clinica=clinica, nome_clinica=nome_clinica)

@app.route('/pagamentos/adicionar', methods=['POST'])
def adicionar_pagamento():
    pessoa_id = int(request.form['pessoa_id'])
    valor_base = float(request.form['valor_base'])
    passagem = float(request.form['passagem']) if request.form['passagem'] else 0
    vale = float(request.form['vale']) if request.form['vale'] else 0
    total_final = valor_base + passagem - vale
    data = request.form['data']
    clinica_param = request.form['clinica']
    clinica_nome = "Belo Horizonte" if clinica_param == 'bh' else "Contagem"
    
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO pagamentos (pessoa_id, valor_base, passagem, vale, total_final, clinica, data) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (pessoa_id, valor_base, passagem, vale, total_final, clinica_nome, data)
    )
    conn.commit()
    conn.close()
    
    flash('Pagamento adicionado com sucesso!', 'success')
    return redirect(url_for('pagamentos', clinica=clinica_param))

@app.route('/api/pessoa/<int:pessoa_id>')
def get_pessoa_dados(pessoa_id):
    """API para buscar dados da pessoa para preenchimento automático"""
    conn = get_db_connection()
    
    # Buscar dados da pessoa
    pessoa = conn.execute('SELECT * FROM pessoas WHERE id = ?', (pessoa_id,)).fetchone()
    
    if not pessoa:
        conn.close()
        return {'error': 'Pessoa não encontrada'}, 404
    
    # Buscar vales do mês atual
    mes_atual = datetime.now().strftime('%Y-%m')
    vales_mes = conn.execute(
        'SELECT COALESCE(SUM(valor), 0) as total FROM vales WHERE pessoa_id = ? AND strftime("%Y-%m", data) = ?',
        (pessoa_id, mes_atual)
    ).fetchone()['total']
    
    conn.close()
    
    dados = {
        'salario': float(pessoa['salario']) if pessoa['salario'] else 0,
        'passagem_padrao': float(pessoa['passagem_padrao']) if pessoa['passagem_padrao'] else 0,
        'vales_mes': float(vales_mes)
    }
    
    return dados

@app.route('/pagamentos/editar/<int:id>', methods=['POST'])
def editar_pagamento(id):
    pessoa_id = int(request.form['pessoa_id'])
    valor_base = float(request.form['valor_base'])
    passagem = float(request.form['passagem']) if request.form['passagem'] else 0
    vale = float(request.form['vale']) if request.form['vale'] else 0
    total_final = valor_base + passagem - vale
    data = request.form['data']
    clinica_param = request.form['clinica']
    clinica_nome = "Belo Horizonte" if clinica_param == 'bh' else "Contagem"
    
    conn = get_db_connection()
    conn.execute(
        'UPDATE pagamentos SET pessoa_id=?, valor_base=?, passagem=?, vale=?, total_final=?, clinica=?, data=? WHERE id=?',
        (pessoa_id, valor_base, passagem, vale, total_final, clinica_nome, data, id)
    )
    conn.commit()
    conn.close()
    
    flash('Pagamento editado com sucesso!', 'success')
    return redirect(url_for('pagamentos', clinica=clinica_param))

@app.route('/pagamentos/excluir/<int:id>')
def excluir_pagamento(id):
    clinica = request.args.get('clinica', 'bh')
    conn = get_db_connection()
    conn.execute('DELETE FROM pagamentos WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    flash('Pagamento excluído com sucesso!', 'success')
    return redirect(url_for('pagamentos', clinica=clinica))

@app.route('/comprovante/<int:pagamento_id>')
def comprovante_pagamento(pagamento_id):
    """Gerar comprovante individual de pagamento"""
    conn = get_db_connection()
    
    # Buscar dados do pagamento
    pagamento = conn.execute(
        '''SELECT p.*, pe.nome, pe.tipo, pe.pix 
           FROM pagamentos p 
           JOIN pessoas pe ON p.pessoa_id = pe.id 
           WHERE p.id = ?''',
        (pagamento_id,)
    ).fetchone()
    
    if not pagamento:
        flash('Pagamento não encontrado!', 'error')
        return redirect(url_for('pagamentos'))
    
    conn.close()
    
    # Calcular valores
    total_bruto = pagamento['valor_base'] + pagamento['passagem']
    
    return render_template('comprovante_pagamento.html',
                         pagamento=pagamento,
                         total_bruto=total_bruto)

@app.route('/folha-pagamento')
def folha_pagamento():
    """Página para gerar folha de pagamento do mês"""
    mes = request.args.get('mes')
    if not mes:
        mes = datetime.now().strftime('%Y-%m')
    
    conn = get_db_connection()
    
    # Pagamentos BH
    pagamentos_bh = conn.execute(
        '''SELECT p.*, pe.nome, pe.tipo, pe.pix 
           FROM pagamentos p 
           JOIN pessoas pe ON p.pessoa_id = pe.id 
           WHERE p.clinica = "Belo Horizonte" AND strftime("%Y-%m", p.data) = ?
           ORDER BY pe.tipo, pe.nome''',
        (mes,)
    ).fetchall()
    
    # Pagamentos Contagem
    pagamentos_contagem = conn.execute(
        '''SELECT p.*, pe.nome, pe.tipo, pe.pix 
           FROM pagamentos p 
           JOIN pessoas pe ON p.pessoa_id = pe.id 
           WHERE p.clinica = "Contagem" AND strftime("%Y-%m", p.data) = ?
           ORDER BY pe.tipo, pe.nome''',
        (mes,)
    ).fetchall()
    
    conn.close()
    
    return render_template('folha_pagamento.html',
                         mes=mes,
                         pagamentos_bh=pagamentos_bh,
                         pagamentos_contagem=pagamentos_contagem)

@app.route('/folha-pagamento/imprimir')
def folha_pagamento_imprimir():
    """Folha de pagamento para impressão A4"""
    mes = request.args.get('mes')
    if not mes:
        mes = datetime.now().strftime('%Y-%m')
    
    conn = get_db_connection()
    
    # Pagamentos BH
    pagamentos_bh = conn.execute(
        '''SELECT p.*, pe.nome, pe.tipo, pe.pix 
           FROM pagamentos p 
           JOIN pessoas pe ON p.pessoa_id = pe.id 
           WHERE p.clinica = "Belo Horizonte" AND strftime("%Y-%m", p.data) = ?
           ORDER BY pe.tipo, pe.nome''',
        (mes,)
    ).fetchall()
    
    # Pagamentos Contagem
    pagamentos_contagem = conn.execute(
        '''SELECT p.*, pe.nome, pe.tipo, pe.pix 
           FROM pagamentos p 
           JOIN pessoas pe ON p.pessoa_id = pe.id 
           WHERE p.clinica = "Contagem" AND strftime("%Y-%m", p.data) = ?
           ORDER BY pe.tipo, pe.nome''',
        (mes,)
    ).fetchall()
    
    conn.close()
    
    return render_template('folha_pagamento_imprimir.html',
                         mes=mes,
                         pagamentos_bh=pagamentos_bh,
                         pagamentos_contagem=pagamentos_contagem)

@app.route('/faturamentos')
def faturamentos():
    conn = get_db_connection()
    faturamentos_list = conn.execute('SELECT * FROM faturamentos ORDER BY data DESC').fetchall()
    conn.close()
    
    return render_template('faturamentos.html', faturamentos=faturamentos_list)

@app.route('/faturamentos/adicionar', methods=['POST'])
def adicionar_faturamento():
    valor = float(request.form['valor'])
    convenio = request.form['convenio']
    data = request.form['data']
    
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO faturamentos (valor, convenio, data) VALUES (?, ?, ?)',
        (valor, convenio, data)
    )
    conn.commit()
    conn.close()
    
    flash('Faturamento adicionado com sucesso!', 'success')
    return redirect(url_for('faturamentos'))

@app.route('/faturamentos/editar/<int:id>', methods=['POST'])
def editar_faturamento(id):
    valor = float(request.form['valor'])
    convenio = request.form['convenio']
    data = request.form['data']
    
    conn = get_db_connection()
    conn.execute(
        'UPDATE faturamentos SET valor=?, convenio=?, data=? WHERE id=?',
        (valor, convenio, data, id)
    )
    conn.commit()
    conn.close()
    
    flash('Faturamento editado com sucesso!', 'success')
    return redirect(url_for('faturamentos'))

@app.route('/faturamentos/excluir/<int:id>')
def excluir_faturamento(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM faturamentos WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    flash('Faturamento excluído com sucesso!', 'success')
    return redirect(url_for('faturamentos'))

@app.route('/fechamento')
def fechamento():
    mes = request.args.get('mes')
    if not mes:
        mes = datetime.now().strftime('%Y-%m')
    
    conn = get_db_connection()
    
    # Médicos (consolidado entre clínicas)
    medicos = conn.execute(
        '''SELECT p.id, p.nome, p.pix,
           COALESCE(SUM(pg.passagem), 0) as total_passagem,
           COALESCE(SUM(pg.valor_base), 0) as total_pagamento,
           COALESCE(SUM(pg.vale), 0) as total_vale,
           COALESCE(SUM(pg.total_final), 0) as total_final
           FROM pessoas p
           LEFT JOIN pagamentos pg ON p.id = pg.pessoa_id AND strftime("%Y-%m", pg.data) = ?
           WHERE p.tipo = 'Médico'
           GROUP BY p.id, p.nome, p.pix
           HAVING total_final > 0
           ORDER BY p.nome''',
        (mes,)
    ).fetchall()
    
    # Funcionários BH
    funcionarios_bh = conn.execute(
        '''SELECT p.id, p.nome, p.pix,
           COALESCE(SUM(pg.passagem), 0) as total_passagem,
           COALESCE(SUM(pg.valor_base), 0) as total_pagamento,
           COALESCE(SUM(pg.vale), 0) as total_vale,
           COALESCE(SUM(pg.total_final), 0) as total_final
           FROM pessoas p
           LEFT JOIN pagamentos pg ON p.id = pg.pessoa_id AND strftime("%Y-%m", pg.data) = ? AND pg.clinica = 'Belo Horizonte'
           WHERE p.tipo = 'Funcionário'
           GROUP BY p.id, p.nome, p.pix
           HAVING total_final > 0
           ORDER BY p.nome''',
        (mes,)
    ).fetchall()
    
    # Funcionários Contagem
    funcionarios_contagem = conn.execute(
        '''SELECT p.id, p.nome, p.pix,
           COALESCE(SUM(pg.passagem), 0) as total_passagem,
           COALESCE(SUM(pg.valor_base), 0) as total_pagamento,
           COALESCE(SUM(pg.vale), 0) as total_vale,
           COALESCE(SUM(pg.total_final), 0) as total_final
           FROM pessoas p
           LEFT JOIN pagamentos pg ON p.id = pg.pessoa_id AND strftime("%Y-%m", pg.data) = ? AND pg.clinica = 'Contagem'
           WHERE p.tipo = 'Funcionário'
           GROUP BY p.id, p.nome, p.pix
           HAVING total_final > 0
           ORDER BY p.nome''',
        (mes,)
    ).fetchall()
    
    # Despesas BH
    despesas_bh = conn.execute(
        'SELECT * FROM despesas WHERE clinica = "Belo Horizonte" AND strftime("%Y-%m", data) = ? ORDER BY data',
        (mes,)
    ).fetchall()
    
    # Despesas Contagem
    despesas_contagem = conn.execute(
        'SELECT * FROM despesas WHERE clinica = "Contagem" AND strftime("%Y-%m", data) = ? ORDER BY data',
        (mes,)
    ).fetchall()
    
    conn.close()
    
    # Calcular totais
    total_medicos = sum([float(m['total_final']) for m in medicos])
    total_funcionarios_bh = sum([float(f['total_final']) for f in funcionarios_bh])
    total_funcionarios_contagem = sum([float(f['total_final']) for f in funcionarios_contagem])
    total_despesas_bh = sum([float(d['valor']) for d in despesas_bh])
    total_despesas_contagem = sum([float(d['valor']) for d in despesas_contagem])
    
    total_geral = total_medicos + total_funcionarios_bh + total_funcionarios_contagem + total_despesas_bh + total_despesas_contagem
    
    return render_template('fechamento.html',
                         mes=mes,
                         medicos=medicos,
                         funcionarios_bh=funcionarios_bh,
                         funcionarios_contagem=funcionarios_contagem,
                         despesas_bh=despesas_bh,
                         despesas_contagem=despesas_contagem,
                         total_medicos=total_medicos,
                         total_funcionarios_bh=total_funcionarios_bh,
                         total_funcionarios_contagem=total_funcionarios_contagem,
                         total_despesas_bh=total_despesas_bh,
                         total_despesas_contagem=total_despesas_contagem,
                         total_geral=total_geral)

@app.route('/fechamento/imprimir')
def fechamento_imprimir():
    mes = request.args.get('mes')
    if not mes:
        mes = datetime.now().strftime('%Y-%m')
    
    conn = get_db_connection()
    
    # Mesmos dados do fechamento
    medicos = conn.execute(
        '''SELECT p.id, p.nome, p.pix,
           COALESCE(SUM(pg.passagem), 0) as total_passagem,
           COALESCE(SUM(pg.valor_base), 0) as total_pagamento,
           COALESCE(SUM(pg.vale), 0) as total_vale,
           COALESCE(SUM(pg.total_final), 0) as total_final
           FROM pessoas p
           LEFT JOIN pagamentos pg ON p.id = pg.pessoa_id AND strftime("%Y-%m", pg.data) = ?
           WHERE p.tipo = 'Médico'
           GROUP BY p.id, p.nome, p.pix
           HAVING total_final > 0
           ORDER BY p.nome''',
        (mes,)
    ).fetchall()
    
    funcionarios_bh = conn.execute(
        '''SELECT p.id, p.nome, p.pix,
           COALESCE(SUM(pg.passagem), 0) as total_passagem,
           COALESCE(SUM(pg.valor_base), 0) as total_pagamento,
           COALESCE(SUM(pg.vale), 0) as total_vale,
           COALESCE(SUM(pg.total_final), 0) as total_final
           FROM pessoas p
           LEFT JOIN pagamentos pg ON p.id = pg.pessoa_id AND strftime("%Y-%m", pg.data) = ? AND pg.clinica = 'Belo Horizonte'
           WHERE p.tipo = 'Funcionário'
           GROUP BY p.id, p.nome, p.pix
           HAVING total_final > 0
           ORDER BY p.nome''',
        (mes,)
    ).fetchall()
    
    funcionarios_contagem = conn.execute(
        '''SELECT p.id, p.nome, p.pix,
           COALESCE(SUM(pg.passagem), 0) as total_passagem,
           COALESCE(SUM(pg.valor_base), 0) as total_pagamento,
           COALESCE(SUM(pg.vale), 0) as total_vale,
           COALESCE(SUM(pg.total_final), 0) as total_final
           FROM pessoas p
           LEFT JOIN pagamentos pg ON p.id = pg.pessoa_id AND strftime("%Y-%m", pg.data) = ? AND pg.clinica = 'Contagem'
           WHERE p.tipo = 'Funcionário'
           GROUP BY p.id, p.nome, p.pix
           HAVING total_final > 0
           ORDER BY p.nome''',
        (mes,)
    ).fetchall()
    
    despesas_bh = conn.execute(
        'SELECT * FROM despesas WHERE clinica = "Belo Horizonte" AND strftime("%Y-%m", data) = ? ORDER BY data',
        (mes,)
    ).fetchall()
    
    despesas_contagem = conn.execute(
        'SELECT * FROM despesas WHERE clinica = "Contagem" AND strftime("%Y-%m", data) = ? ORDER BY data',
        (mes,)
    ).fetchall()
    
    conn.close()
    
    # Calcular totais
    total_medicos = sum([float(m['total_final']) for m in medicos])
    total_funcionarios_bh = sum([float(f['total_final']) for f in funcionarios_bh])
    total_funcionarios_contagem = sum([float(f['total_final']) for f in funcionarios_contagem])
    total_despesas_bh = sum([float(d['valor']) for d in despesas_bh])
    total_despesas_contagem = sum([float(d['valor']) for d in despesas_contagem])
    
    total_geral = total_medicos + total_funcionarios_bh + total_funcionarios_contagem + total_despesas_bh + total_despesas_contagem
    
    return render_template('fechamento_imprimir.html',
                         mes=mes,
                         medicos=medicos,
                         funcionarios_bh=funcionarios_bh,
                         funcionarios_contagem=funcionarios_contagem,
                         despesas_bh=despesas_bh,
                         despesas_contagem=despesas_contagem,
                         total_medicos=total_medicos,
                         total_funcionarios_bh=total_funcionarios_bh,
                         total_funcionarios_contagem=total_funcionarios_contagem,
                         total_despesas_bh=total_despesas_bh,
                         total_despesas_contagem=total_despesas_contagem,
                         total_geral=total_geral)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)