#Chargement des bibs
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask import jsonify
import pymysql
from flask_caching import Cache
from sqlalchemy.orm.exc import UnmappedInstanceError


#Configuration de la connection avec la base de donnees MySQL
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root:@localhost/db_task'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

#Configuration de la connection avec la base de donnees Redis
app.config['CACHE_TYPE'] = 'redis'
app.config['CACHE_REDIS_URL'] = 'redis://localhost:6379/0'  
app.config['CACHE_KEY_PREFIX'] = ''

cache = Cache(app)
   
class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_name = db.Column(db.String(255), nullable=False)
    task_description = db.Column(db.Text, nullable=False)
    task_due_date = db.Column(db.Date, nullable=False)
    task_priority = db.Column(db.Enum('faible', 'moyenne', 'élevée'), nullable=False)
    task_status = db.Column(db.Enum('not_done', 'done'), default='not_done', nullable=False)
    def __repr__(self):
        return f'<Task {self.task_name}>'
    def to_dict(self):
        return {
            'id': self.id,
            'task_name': self.task_name,
            'task_description': self.task_description,
            'task_due_date': self.task_due_date,
            'task_priority': self.task_priority,
            'task_status': self.task_status
        }
        
@app.errorhandler(500)
def internal_server_error(e):
    return "Internal Server Error", 500  

@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html')  
  
@app.route('/create_task', methods=['GET', 'POST'])
def create_task():
    if request.method == 'POST':
        task_name = request.form['task-name']
        task_description = request.form['task-description']
        task_due_date = request.form['task-due-date']
        task_priority = request.form['task-priority']

        
        existing_task = Task.query.filter_by(task_name=task_name).first()

        if existing_task is None:
            new_task = Task(
                task_name=task_name,
                task_description=task_description,
                task_due_date=task_due_date,
                task_priority=task_priority
            )
            db.session.add(new_task)
            db.session.commit()

            # Ajouter la nouvelle tâche à Redis
                        # Nouvelle logique pour ajouter une tâche sans écraser les données existantes
            tasks_from_cache = cache.get('tasks') or []

            # Vérifier si la tâche existe déjà dans la liste
            task_exists = any(task['id'] == new_task.id for task in tasks_from_cache)

            if not task_exists:
                tasks_from_cache.append(new_task.to_dict())
                cache.set('tasks', tasks_from_cache)


    return redirect(url_for('tasks'))

#@cache.cached(timeout=60) 
@app.route('/tasks')
def tasks():
    #tasks = Task.query.all()
    tasks_from_cache = cache.get('tasks')
    if tasks_from_cache is None:
        # Si les tâches ne sont pas en cache, récupérez-les depuis la base de données
        tasks_from_db = Task.query.all()
        tasks_for_cache = [task.to_dict() for task in tasks_from_db]
        cache.set('tasks', tasks_for_cache)
        tasks = tasks_for_cache
    else:
        tasks = tasks_from_cache
    return render_template('tasks.html', tasks=tasks)

@app.route('/update_task/<int:task_id>', methods=['POST'])
def update_task(task_id):
    
    task = Task.query.get(task_id)
    task_name = task.task_name
    task_description = task.task_description
    task_due_date = task.task_due_date
    task_priority = task.task_priority
    
    return render_template('update_task.html', task=task)


@app.route('/update_task_after/<int:task_id>', methods=['POST'])
def update_task_after(task_id):
    # Récupérer les valeurs du formulaire
    new_task_name = request.form['new-task-name']
    new_task_description = request.form['new-task-description']
    new_task_due_date = request.form['new-task-due-date']
    new_task_priority = request.form['new-task-priority']

    # Mettre à jour la tâche dans la base de données avec les nouvelles valeurs
    task = Task.query.get(task_id)
    task.task_name = new_task_name
    task.task_description = new_task_description
    task.task_due_date = new_task_due_date
    task.task_priority = new_task_priority

    # Enregistrer les modifications dans la base de données
    db.session.commit()

    # Mettre à jour la liste dans Redis
    tasks_from_cache = cache.get('tasks')

    if tasks_from_cache is not None:
        # Mettre à jour les informations de la tâche dans la liste dans Redis
        for cached_task in tasks_from_cache:
            if cached_task['id'] == task_id:
                cached_task['task_name'] = new_task_name
                cached_task['task_description'] = new_task_description
                cached_task['task_due_date'] = new_task_due_date
                cached_task['task_priority'] = new_task_priority

        cache.set('tasks', tasks_from_cache)

    # Rediriger vers la page tasks ou une autre page appropriée
    return redirect(url_for('tasks'))

@app.route('/tasks/delete/<int:task_id>', methods=['GET', 'POST'])
def delete_task(task_id):
    # Récupérer la tâche à supprimer
    task = Task.query.get(task_id)

    if task is not None:
        try:
            # Supprimer la tâche de la base de données
            db.session.delete(task)
            db.session.commit()

            # Supprimer la tâche de la liste dans Redis
            tasks_from_cache = cache.get('tasks')

            if tasks_from_cache is not None:
                # Retirer la tâche de la liste dans Redis
                tasks_from_cache = [task for task in tasks_from_cache if task['id'] != task_id]
                cache.set('tasks', tasks_from_cache)

            return redirect(url_for('tasks'))
        except UnmappedInstanceError as e:
            # Gérer l'erreur si la tâche n'est pas mappée à la base de données
            print(f"Error deleting task: {e}")
            db.session.rollback()  # Annuler les modifications en cas d'erreur
    else:
        print(f"Task with ID {task_id} not found.")

    return redirect(url_for('tasks'))


@app.route('/update_status/<int:task_id>', methods=['POST'])
def update_status(task_id):
    task = Task.query.get(task_id)
    if task:
        # Inverser l'état de la tâche (fait ou non fait)
        if task.task_status == 'not_done':
            task.task_status = 'done'
        else:
            task.task_status = 'not_done'

        # Enregistrer les modifications dans la base de données
        db.session.commit()

        # Mettre à jour la liste dans Redis
        tasks_from_cache = cache.get('tasks')

        if tasks_from_cache is not None:
            # Mettre à jour le statut de la tâche dans la liste dans Redis
            for cached_task in tasks_from_cache:
                if cached_task['id'] == task_id:
                    cached_task['task_status'] = task.task_status

            cache.set('tasks', tasks_from_cache)

        
    else:
        return {'message': 'Tâche non trouvée'}, 404

    
@app.route('/add_task', methods=['GET', 'POST'])
def add_task():
    return redirect(url_for('index'))
    
    
##############################################
if __name__ == '__main__':
    app.run()