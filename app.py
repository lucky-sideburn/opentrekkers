# coding=utf-8 
from PIL import Image as PILImage
from PIL import ImageEnhance as PILImageEnhance
from PIL import ImageDraw as PILImageDraw
from PIL import ImageFont as PILImageFont
from datetime import datetime
import time
import qrcode
import uuid 
import os
import pymongo
import string
import secrets
import random
import smtplib
import base64
import bcrypt
import logging
import img2pdf
import markdown
import sendgrid
from sendgrid.helpers.mail import *

from urllib.parse import urljoin
from flask import Flask, render_template, request, send_file, redirect, url_for, Response, session
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user, current_user
from flask_avatars import Avatars
from flask_appbuilder import Model
from pymongo import MongoClient
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MONGO_DBNAME'] = os.environ['MONGO_DBNAME']
app.config['MONGO_URI'] = os.environ['MONGO_URI']
app.config['SECRET_KEY'] = os.environ['FLASK_SECRET_KEY']
app.config['SITE_URL'] = os.environ['SITE_URL']
app.config['SENDGRID_API_KEY'] = os.environ['SENDGRID_API_KEY']
app.config['VOUCHER_PROPOSAL_RECEIVER'] = os.environ['VOUCHER_PROPOSAL_RECEIVER']

#app.config['UPLOAD_FOLDER'] = './static'
app.config['IMAGE_UPLOAD_FOLDER'] = os.environ['IMAGE_UPLOAD_FOLDER']
app.config['CARDS_LOCAL_FOLDER'] = os.environ['CARDS_LOCAL_FOLDER']

app.config['IMAGES_BASE_URL'] = app.config['SITE_URL'] + "/static/images"
app.config['CARDS_BASE_URL'] = app.config['SITE_URL'] + "/static/cards"

avatars = Avatars(app)
client =  MongoClient(app.config['MONGO_URI'])

class User(UserMixin):
    def __init__(self, username, password, id, active=True):
        self.id = id
        self.username = username
        self.password = password
        self.active = active

    def get_id(self):
        return self.id

    def is_active(self):
        return self.active

    def get_auth_token(self):
        return make_secure_token(self.username , key='secret_key')

class UsersRepository:
    def __init__(self):
        self.users = dict()
        self.users_id_dict = dict()
        self.identifier = 0
    
    def save_user(self, user):
        self.users_id_dict.setdefault(user.id, user)
        self.users.setdefault(user.username, user)
    
    def get_user(self, username):
        return self.users.get(username)
    
    def get_user_by_id(self, userid):
        return self.users_id_dict.get(userid)
    
    def next_index(self):
        self.identifier +=1
        return self.identifier

users_repository = UsersRepository()

def randomString(stringLength=10):
    lettersAndDigits = string.ascii_lowercase + string.digits
    return ''.join(random.choice(lettersAndDigits) for i in range(stringLength))

@app.route("/show_itinerary", methods = ['GET'])
def show_itinerary():
  if request.args.get('id'):
    itinerary_id = request.args.get('id')
  return render_template('show.html', itineraries=get_itineraries(), last=get_last_position(), itinerary_id=itinerary_id)

@app.route("/", methods = ['POST', 'GET'])
def main():
  return render_template('index.html', itineraries=get_itineraries(), last=get_last_position(), itinerary_id='')

@app.route("/chi_siamo", methods = ['GET'])
def chi_siamo():
  return render_template('chi_siamo.html')

@app.route("/access_denied", methods = ['GET'])
def access_denied():
  return render_template('access_denied.html')

@app.route("/come_funziona", methods = ['GET'])
def come_funziona():
  return render_template('come_funziona.html')

@app.route("/manifesto", methods = ['GET'])
def manifesto():
  return render_template('manifesto.html')

@app.route("/livelli", methods = ['GET'])
def livelli():
  return render_template('livelli.html')

@app.route("/build_itinerary", methods = ['GET'])
def build_itinerary():
  return render_template('build_itinerary.html', itineraries=get_itineraries(), last=get_last_position())

@app.route("/control_itinerary", methods = ['GET'])
def control_itinerary():
  return render_template('control_itinerary.html', itineraries=get_itineraries(), last=get_last_position())

@app.route("/voucher_proposal/create", methods = ['POST'])
def create_voucher_proposal():
  text = f"Itinerario: {request.form['itineray_of_proposal'].replace('suggest_voucher_', '')}\n\
Email: {request.form['shop_email'].replace('@', '[at]').replace('.', '[dot]')}\n\
Messaggio: {request.form['shop_description']}"
  send_email('Voucher per itinerario', text, app.config['VOUCHER_PROPOSAL_RECEIVER'])
  message="Grazie per averci contattato e per la proposta di associazione voucher. Ti contatteremo appena possibile."
  return render_template('index.html', itineraries=get_itineraries(), last=get_last_position(), itinerary_id='', message=message)

@app.route('/logout')
def logout():
   print("Logout " + session['username'])
   session.pop('username', None)
   return redirect(url_for('main'))

@app.route('/login', methods=['POST'])
def login():
    db = client[app.config['MONGO_DBNAME']]
    collection = db['users']
    login_user = collection.find_one({'name' : request.form['username']})
    if login_user:
        if bcrypt.hashpw(request.form['pass'].encode('utf-8'), login_user['password']) == login_user['password']:
            session['username'] = request.form['username']

    return redirect(url_for('main'))

@app.route('/register', methods=['POST', 'GET'])
def register():
  
  db = client[app.config['MONGO_DBNAME']]
  collection = db['users']

  if request.method == 'POST':
      existing_user = collection.find_one({'name' : request.form['username']})
      if existing_user is None:
          hashpass = bcrypt.hashpw(request.form['pass'].encode('utf-8'), bcrypt.gensalt())
          collection.insert({'name' : request.form['username'], 'password' : hashpass})
          session['username'] = request.form['username']
          return redirect(url_for('main'))

  return redirect(url_for('main'))

def allowed_file(filename):
  return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'}

def create_voucher_img(author, partecipant_name, partecipants_count, shop_name, shop_address, shop_email, shop_telephone_number, intinerary_name, itinerary_id, voucher_id, voucher_token, voucher_content, voucher_type, expiry_date):
  background_color = "#278d8f"
  img = PILImage.new('RGB', (1280, 960), color=background_color)
  d = PILImageDraw.Draw(img)
  fill_color = 'white'
  font = PILImageFont.truetype("Retro_Gaming.ttf",18)
  right_position = 150

  logo = "opentrekkers.it"
  logo_font = PILImageFont.truetype("Retro_Gaming.ttf",32)
  d.text((580,2), logo, fill='yellow', font=logo_font)

  intinerary_header = "Itinerario\n"
  intinerary_header_font = PILImageFont.truetype("Retro_Gaming.ttf",26)
  d.text((right_position,110), intinerary_header, fill='white', font=intinerary_header_font)

  itinerary = intinerary_name
  itinerary_font = PILImageFont.truetype("Retro_Gaming.ttf",26)
  d.text((right_position,140), itinerary, fill='yellow', font=itinerary_font)

  
  if voucher_type == "Guida Turistica":
    usage = "con"
    where = ""
  else:
    usage = "da"
    where = f"presso {shop_address}"

  card_text = f"Questo voucher è per {partecipant_name}\nUsare {usage} {shop_name} {where}\n\nEntro il: {expiry_date}\nPartecipanti: {partecipants_count}\n\
Tipo di voucher: sconto per {voucher_type}\n\
Email: {shop_email}\nTelefono: {shop_telephone_number}\n\
Contenuto:\n{voucher_content}\n" 
  
  card_text_font = PILImageFont.truetype("Retro_Gaming.ttf",18)
  d.text((right_position,240), card_text, fill=fill_color, font=card_text_font)

  footer = f"\n\nTi ricordiamo di chiamare {shop_name} per prenotare il tuo posto ({partecipants_count} persone)\n\
Mostra il QR code a {shop_name} che lo userà per validare il tuo voucher.\n\
Grazie per aver scelto un itinerario su Opentrekkers.it e buona strada!\n\n"

  footer_font = PILImageFont.truetype("Retro_Gaming.ttf",16)
  d.text((right_position,440), footer, fill='white', font=footer_font)

  img.save('static/cards/' + voucher_id + '-text.png')
  
  qr = qrcode.QRCode(
      version=1,
      error_correction=qrcode.constants.ERROR_CORRECT_L,
      box_size=4,
      border=2,
  )

  qr_data = urljoin(app.config['SITE_URL'], f"/voucher/verify?itinerary_id={itinerary_id}&voucher_id={voucher_id}&voucher_token={voucher_token}")
  print(qr_data)
  qr.add_data(qr_data)
  qr.make(fit=True)

  img = qr.make_image(fill_color=fill_color, back_color=background_color)
  img.save('static/cards/' + voucher_id + '-qr.png')

  images = [PILImage.open(x) for x in ['static/cards/' + voucher_id + '-text.png', 'static/cards/' + voucher_id + '-qr.png']]
  widths, heights = zip(*(i.size for i in images))
  total_width = sum(widths)
  max_height = max(heights)

  new_im = PILImage.new('RGB', (total_width, max_height), color=background_color)

  x_offset = 0
  cnt = 0
  for im in images:
    if cnt > 0:
      new_im.paste(im, (950, 200))
    else:
      new_im.paste(im, (x_offset,0))
    x_offset += im.size[0]
    cnt = cnt + 1

  final_image = 'static/cards/' + voucher_id + '.png'

  pdf_path = app.config['CARDS_LOCAL_FOLDER'] + '/' + voucher_id + '.pdf'
  pdf_url = app.config['CARDS_BASE_URL'] + '/' + voucher_id + '.pdf'

  new_im.save(final_image, format="png")
  im = PILImage.open(final_image)
  enhancer = PILImageEnhance.Brightness(im)
  enhanced_im = enhancer.enhance(0.9)
  enhanced_im.save(final_image, format="png")
  
  with open(pdf_path, "wb") as f:
    f.write(img2pdf.convert(final_image))

  return pdf_url

def generate_vouchers(intineray_name, vouchers_count):
  app.logger.info('Generate Vouchers for the itinerary %s', intineray_name)
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  docs = collection.find().sort("position")
  filter = { "name":  intineray_name }  
  
  new_value = { "$set": { 'vouchers': [] } } 
  collection.update_one(filter, new_value)  

def get_itinerary(name):
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  itinerary = collection.find_one({ "name": name })
  return itinerary

def get_itinerary_from_id(itinerary_id):
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  itinerary = collection.find_one({ "itinerary_id": itinerary_id })
  return itinerary

def get_itineraries():
  app.logger.info('Searching itineraries...')
  itineraries = []
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  docs = collection.find().sort("position")
  for item in docs:
    itineraries.append(item)
  app.logger.info('Found %s itineraries', str(len(itineraries)))

  return itineraries

def get_last_position():
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  docs = collection.find().sort("position")
  position = 0
   
  for item in docs:
    last_item = item
    position = last_item["position"]

  app.logger.info('Last position is %s', position)
  return position

def delete_itinerary(name):
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  collection.delete_one({"name": name})

def set_itineray_order(action, name):
  itineraries = []
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  docs = collection.find()
  itinerary = collection.find_one({ "name": name })
  
  for item in docs:
    itineraries.append(item)

  if len(itineraries) == 0:
    return 1
  
  elif action == "new":
    return get_last_position() + 1

  elif action == "up":
    app.logger.info('Moving up the itinerary %s', itinerary["name"])
    filter = { "position":  itinerary["position"] - 1  }  
    new_value = { "$set": { 'position': itinerary["position"] } } 
    collection.update_one(filter, new_value)  

    doc = collection.find_one({"name": name})
    filter = { "name": itinerary["name"] }  
    new_value = { "$set": { 'position': itinerary["position"] - 1 } } 
    collection.update_one(filter, new_value)  


  elif action == "down":
    filter = { "position":  itinerary["position"]  + 1  }  
    new_value = { "$set": { 'position': itinerary["position"] } } 
    collection.update_one(filter, new_value) 

    doc = collection.find_one({"name": name})
    filter = { "name": itinerary["name"] }  
    new_value = { "$set": { 'position': itinerary["position"] + 1 } } 
    collection.update_one(filter, new_value)  

def set_itinerary_property(prop, name):
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  filter = { "name": name }  
  new_value = { "$set": prop } 
  collection.update_one(filter, new_value)  

@app.route('/search/itinerary',methods = ['POST'])
def search_itinerary():
  itineraries = []
  message=''
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  for item in collection.find({"$text": {"$search": request.form["search_text"]}}):
    itineraries.append(item)
  
  if len(itineraries) == 0:
    itineraries=get_itineraries()
    message = 'Gentile utente, ancora non abbiamo un itinerario che soddisfi la tua ricerca. Stiamo sviluppando altri itinerari, ma nel frattempo ti proponiamo questi qui di seguito.'
  return render_template('index.html', itineraries=itineraries, last=get_last_position(), itinerary_id='', message=message)

def auth_voucher(voucher_id, voucher_token, itinerary_id):
  itinerary = get_itinerary_from_id(itinerary_id)
  app.logger.info('Checking authentication of voucher_id %s for itinerary_name: %s', voucher_id, itinerary["name"])
  for voucher in itinerary["vouchers_list"]:
    if voucher["voucher_id"] == voucher_id and voucher["voucher_token"] == voucher_token:
      app.logger.info('Voucher %s authenticated!', voucher_id)
      return True
  app.logger.info('Voucher %s is not authenticated!', voucher_id)
  return False

def get_voucher_status(voucher_id, itinerary_id):
  app.logger.info('Changing status of the voucher %s', voucher_id)
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  itinerary = get_itinerary_from_id(itinerary_id)
  for voucher in itinerary["vouchers_list"]:
    if voucher["voucher_id"] == voucher_id:
      return voucher["status"]
    
def change_voucher_status(voucher_id, itinerary_id, status):
  app.logger.info('Changing status of the voucher %s to %s', voucher_id, status)
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  itinerary = get_itinerary_from_id(itinerary_id)
  app.logger.info('The voucher %s is related to the itinerary %s', voucher_id, itinerary["name"])
  cnt=0
  for voucher in itinerary["vouchers_list"]:
    if voucher["voucher_id"] == voucher_id:
      app.logger.info('Found voucher %s in the vouchers list of %s', voucher_id, itinerary["name"])
      itinerary["vouchers_list"][cnt]["status"] = status
      filter = { "name": itinerary["name"] }  
      new_value = { "$set": { "vouchers_list": itinerary["vouchers_list"]} } 
      collection.update_one(filter, new_value)
    else:
      cnt+=1
    
def get_vouchers(itinerary_name):
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  itinerary = get_itinerary(itinerary_name)
  return itinerary["vouchers"]

def get_voucher(voucher_id, itinerary_id):
  itinerary = get_itinerary_from_id(itinerary_id)
  for voucher in itinerary["vouchers_list"]:
    if voucher["voucher_id"] == voucher_id:
      return voucher
  return None

def vouchers_reduce(itinerary_name):
  vouchers = 0
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  itinerary = get_itinerary(itinerary_name)
  if itinerary["vouchers"] > 0:
    app.logger.info('Deleting one voucher slot from the itinerary %s', itinerary_name)
    vouchers = itinerary["vouchers"] - 1
    filter = { "name": itinerary_name }  
    new_value = { "$set": { "vouchers": vouchers} } 
    collection.update_one(filter, new_value)
  else:
    app.logger.info('The itinerary %s has 0 available vouchers', itinerary_name)

def send_email(subject, text, recipient):
  app.config['SENDGRID_API_KEY']
  sg = sendgrid.SendGridAPIClient(api_key=app.config['SENDGRID_API_KEY'])
  from_email = Email("opentrekkers@gmail.com")
  to_email = To(recipient)
  subject = subject
  content = Content("text/plain", text)
  mail = Mail(from_email, to_email, subject, content)
  response = sg.client.mail.send.post(request_body=mail.get())

  app.logger.info('Email response status code: %s', response.status_code)
  app.logger.info('Email response body: %s', response.body)
  app.logger.info('Email response headers: %s', response.headers)

@app.route('/voucher/reserve', methods=['GET'])
def voucher_reserve():
  voucher_id = request.args.get('voucher_id')
  voucher_token = request.args.get('voucher_token')
  itinerary_id = request.args.get('itinerary_id')
  if auth_voucher(voucher_id, voucher_token, itinerary_id):
    change_voucher_status(voucher_id, itinerary_id, 'reserved')
    voucher = get_voucher(voucher_id, itinerary_id)
    return render_template('voucher_reserved.html', voucher_authenticated=True, voucher=voucher)
  else:
    return redirect(url_for('access_denied'))

@app.route('/voucher/verify', methods=['GET'])
def voucher_verify():
  voucher_id = request.args.get('voucher_id')
  voucher_token = request.args.get('voucher_token')
  itinerary_id = request.args.get('itinerary_id')
  if auth_voucher(voucher_id, voucher_token, itinerary_id):
    voucher = get_voucher(voucher_id, itinerary_id)
    itinerary = get_itinerary_from_id(itinerary_id)
    if get_voucher_status(voucher_id, itinerary_id) == 'verified':
      return render_template('voucher_verified.html', voucher_authenticated=True, voucher=voucher, itinerary=itinerary, already_verified=True)
    else:  
      change_voucher_status(voucher_id, itinerary_id, 'verified')
      return render_template('voucher_verified.html', voucher_authenticated=True, voucher=voucher, itinerary=itinerary)
  else:
    return redirect(url_for('access_denied'))

@app.route("/voucher_reserved", methods = ['POST', 'GET'])
def voucher_reserved():
  return render_template('voucher_reserved.html')

@app.route("/voucher_verified", methods = ['POST', 'GET'])
def voucher_verified():
  return render_template('voucher_verified.html')


@app.route('/voucher/create', methods=['POST', 'GET'])
def create_voucher():
  app.logger.info('Creating a voucher for the itinerary %s', request.form['itinerary_of_voucher'])
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  itinerary = collection.find_one({"name": request.form['itinerary_of_voucher']})
  partecipant_name = request.form['partecipant_name']
  partecipant_email = request.form['partecipant_email']

  if itinerary["vouchers"] == 0:
    app.logger.info(f"The itinerary {itinerary['name']} has not vouchers")
    message = f"Grazie {partecipant_name}! Purtroppo i voucher per {itinerary['name']} sono terminati! Ci dispiace molto, ma ti invitiamo a seguirci per trovare nuovi voucher e nuovi itinerari!"
    return render_template('index.html', itineraries=get_itineraries(), message=message, itinerary_id='')
    #return redirect(url_for('main'))

  app.logger.info('Itinerary related to the voucher creation that has been requested: %s', itinerary)
  author = itinerary['author']
  shop_name = itinerary['shop_name']
  shop_address = itinerary['shop_address']
  shop_telephone_number = itinerary['shop_telephone_number']
  shop_email = itinerary['shop_email']
  intinerary_name = request.form['itinerary_of_voucher']
  itinerary_id = itinerary['itinerary_id']
  voucher_id = str(uuid.uuid4())
  voucher_token = randomString(20)
  expiry_date = itinerary['expiry_date'] 
  partecipants_count = itinerary['partecipants']
  voucher_content = itinerary['voucher_content']
  voucher_type = itinerary['voucher_type']
  app.logger.info('Going to create a voucher card for the itinerary %s request by %s (email address: %s)', intinerary_name,partecipant_name, partecipant_email)

  pdf_url = create_voucher_img(author, partecipant_name, partecipants_count, shop_name, shop_address, shop_email, shop_telephone_number, intinerary_name, itinerary_id, voucher_id, voucher_token, voucher_content, voucher_type, expiry_date)
  voucher_reserve_url = app.config['SITE_URL'] + f"/voucher/reserve?itinerary_id={itinerary_id}&voucher_id={voucher_id}&voucher_token={voucher_token}"
  voucher_verify_url = app.config['SITE_URL'] + f"/voucher/verify?itinerary_id={itinerary_id}&voucher_id={voucher_id}&voucher_token={voucher_token}"
  doc = collection.find_one({"name": intinerary_name})
  vouchers_list = doc["vouchers_list"]
  vouchers_list.append({
    "voucher_id": voucher_id,
    "voucher_token": voucher_token,
    "itinerary_name": intinerary_name,
    "beneficiary": partecipant_name,
    "beneficiary_email": partecipant_email,
    "url": pdf_url,
    "expiry_date": expiry_date,
    "status": "created",
    "status_list": "created, reserved, verified, expired",
    "partecipant_email": partecipant_email,
    "shop_telephone_number": shop_telephone_number,
    "voucher_reserve_url": voucher_reserve_url,
    "voucher_verify_url": voucher_verify_url
  })
  filter = { "name":  intinerary_name } 
  new_value = { "$set": { 'vouchers_list': vouchers_list } } 
  collection.update_one(filter, new_value)  
  vouchers_reduce(intinerary_name)
  message = f"Grazie {partecipant_name}! Ti abbiamo inviato una mail di conferma con un link per scaricare il voucher."
  subject = f"Il tuo voucher"
  text = f"Ciao {partecipant_name},\n\nDi seguito il link al voucher dell'itinerario \"{intinerary_name}\" da spendere presso {shop_name}.\n\n{voucher_reserve_url}\n\n\nGrazie ancora per aver scelto Opentrekkers.it!"
  send_email(subject, text, partecipant_email)  
  return render_template('index.html', itineraries=get_itineraries(), last=get_last_position(), itinerary_id='', message=message)

@app.route('/itinerary/manage', methods=['POST'])
def manage_itinerary():
  app.logger.info('Requested an action for changing an itinerary %s', request.form['name'])
  #app.logger.info('%s', request.form.get('up', None))
  if request.form.get('up', None):
    app.logger.info('Request for moving up the itinerary %s', request.form['name'])
    set_itineray_order("up", request.form['name'])
  
  elif request.form.get('down', None):
    app.logger.info('Request for moving down the itinerary')
    set_itineray_order("down", request.form['name'])

  elif request.form.get('enable', None):
    app.logger.info('Request for enable the itinerary')
    set_itinerary_property({"status": "enabled"}, request.form['name'])

  elif request.form.get('disable', None):
    app.logger.info('Request for disable the itinerary')
    set_itinerary_property({"status": "disabled"}, request.form['name'])

  elif request.form.get('delete', None):
    app.logger.info('Request for delete the itinerary')
    delete_itinerary(request.form['name'])

  elif request.form.get('modify', None):
    app.logger.info('Request for modify the itinerary')
    change_itinerary = get_itinerary(request.form['name'])
    
    return render_template('build_itinerary.html', itinerary=get_itinerary(request.form['name']), modify=True)

  #return redirect(url_for('main'))
  return render_template('control_itinerary.html', itineraries=get_itineraries(), last=get_last_position())


@app.route('/itinerary/create', methods=['POST'])
def create_itinerary():
  file = request.files['file']
  db = client[app.config['MONGO_DBNAME']]
  collection = db['itinerary']
  docs_count = collection.count_documents({"name": request.form['name']})
  app.logger.info('%s', str(docs_count))
  itinerary_name = request.form['name']
  voucher = {}
  voucher_attrs = ['vouchers', 'voucher_content', 'shop_name', 'shop_address', 'shop_email', 'shop_telephone_number', 'expiry_date']

  app.logger.info(request.form)

  if not "modify" in request.form and docs_count > 0:
    itinerary_name = itinerary_name + ' (' + str(docs_count + 1 ) + ')'

  if request.form['voucher_type'] == "Nessuno":
    for attr in voucher_attrs:
      if attr == 'vouchers':
        voucher[attr] = 0
      else:
        voucher[attr] = ''
  else:
    for attr in voucher_attrs:
      voucher[attr] = request.form[attr]

  if session and session['username'] == 'admin':
    status = "enabled"
  else:
    status = "disabled"

  itinerary = {
    "name": itinerary_name,
    "expiry_date": voucher['expiry_date'],
    "starting_point": request.form['starting_point'],
    "partecipants": request.form['partecipants'],
    "short_description": request.form['short_description'],
    "stages": markdown.markdown(request.form['stages']),
    "stages_markdown": request.form['stages'],
    "equipment": markdown.markdown(request.form['equipment']),
    "equipment_markdown": request.form['equipment'],
    "author": request.form['author'],
    "duration": request.form['duration'],
    "vouchers": int(voucher['vouchers']),
    "voucher_content": voucher['voucher_content'],
    "vouchers_list": [],
    "status": status,
    "itinerary_id": str(uuid.uuid4()),
    "shop_name": voucher['shop_name'],
    "shop_address": voucher['shop_address'],
    "position": set_itineray_order("new", request.form['name']),
    "level": request.form['level'],
    "voucher_type": request.form['voucher_type'],
    "shop_email": voucher['shop_email'],
    "shop_telephone_number": voucher['shop_telephone_number'],
    "google_maps": request.form['google_maps']
  }

  if file and allowed_file(file.filename):
    app.logger.info('File %s', file)
    filename = secure_filename(file.filename)
    name, ext = os.path.splitext(filename)
    filename =  str(uuid.uuid4()) + ext
    file.save(os.path.join(app.config['IMAGE_UPLOAD_FOLDER'], filename))
    itinerary["image"] = app.config['IMAGES_BASE_URL'] + '/' + filename
    app.logger.info('Itinerary image of %s is %s (URI is %s)', itinerary_name, filename, itinerary["image"])


  if "modify" in request.form:
    app.logger.info('Changing itinerary %s', itinerary_name)
    app.logger.info('Changing itinerary %s', itinerary)
    collection.update_one({"name": itinerary["name"]}, {'$set': itinerary})     
    #return redirect(url_for('main'))
    return render_template('index.html', itineraries=get_itineraries(), last=get_last_position(), itinerary_id='', message='Itinerario modificato con successo')

  app.logger.info('Creating itinerary %s', itinerary_name)
  post_id = collection.insert_one(itinerary).inserted_id

  if session and session['username'] == 'admin':
    message = "Itinerario creato con successo!"
  else:
    message = "Grazie per averci inviato il tuo itinerario! Ti contatteremo appena possibile"

  return render_template('index.html', itineraries=get_itineraries(), last=get_last_position(), itinerary_id='', message=message)
  #return redirect(url_for('main'))

@app.context_processor
def inject_stage_and_region():
  return dict(site_url=app.config['SITE_URL'])

@app.after_request
def add_header(r):
    """
    Add headers to both force latest IE rendering engine or Chrome Frame,
    and also to cache the rendered page for 10 minutes.
    """
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    r.headers['Cache-Control'] = 'public, max-age=0'
    return r

if __name__ == "__main__":
    app.run(host='0.0.0.0')

