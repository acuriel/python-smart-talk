from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from datetime import datetime
import uuid
import os, sys
import re
import argparse
from marshmallow import ValidationError, validates, fields


# Init the app
app = Flask(__name__)
base_dir = os.path.abspath(os.path.dirname(__file__))


# DB
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(base_dir, 'db.sqlite')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# init the db
db = SQLAlchemy(app)

# Init ma
ma = Marshmallow(app)


# Configuration constants
STATUS_OPTIONS = ("online", "offline")
GATEWAY_LIMIT = 10
ip_regex = re.compile(r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$')


def generate_uuid():
    return str(uuid.uuid4())

# Models
class Gateway(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    serial = db.Column(db.String(100), unique=True)
    name = db.Column(db.String(100))
    address = db.Column(db.String(15))

    def __init__(self, serial, name, address):
        self.serial = serial
        self.name = name
        self.address = address


class Peripheral(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(120), default=generate_uuid)
    vendor = db.Column(db.String(50))
    date = db.Column(db.Date, default=datetime.utcnow)
    status = db.Column(db.Enum(*STATUS_OPTIONS, name="peripheral_status"))
    gateway_id = db.Column(db.Integer, db.ForeignKey("gateway.id"))
    gateway = db.relationship("Gateway", backref="peripherals")

    def __init__(self, vendor, status, gateway_id):
        self.vendor = vendor
        self.status = status
        self.gateway_id = gateway_id


# Schemas
class GatewaySchema(ma.ModelSchema):
    serial = fields.String(required=True)
    name = fields.String(required=True)
    address = fields.String(required=True)

    class Meta:
        model = Gateway

    @validates('serial')
    def validate_serial(self, value):
        if Gateway.query.filter_by(serial=value).first() is not None:
            raise ValidationError('Value must be unique')

    @validates('address')
    def validate_address(self, value):
        if not ip_regex.match(value):
            raise ValidationError('Not a valid IPv4 address')

    peripherals = ma.List(ma.HyperlinkRelated("peripheral_detail"))
    _links = ma.Hyperlinks(
        {"self": ma.URLFor("gateway_detail", id="<id>"), "collection": ma.URLFor("list_gateways")}
    )


class PeripheralSchema(ma.ModelSchema):
    class Meta:
        model = Peripheral

    vendor = fields.String(required=True)
    status = fields.String(required=True)
    gateway_id = fields.Int(required=True, load_only=True)
    uuid = fields.String(dump_only=True)
    date = fields.String(dump_only=True)

    @validates('status')
    def validate_status(self, value):
        if value not in STATUS_OPTIONS:
            raise ValidationError('Not a valid status')

    @validates('gateway_id')
    def validate_serial(self, value):
        if Peripheral.query.filter_by(gateway_id=value).count() >= GATEWAY_LIMIT:
            raise ValidationError('Maximum number of peripherals per gateway reached.')

    gateway = ma.HyperlinkRelated("gateway_detail")
    _links = ma.Hyperlinks(
        {"self": ma.URLFor("peripheral_detail", id="<id>"), "collection": ma.URLFor("list_peripheral")}
    )


gateway_schema = GatewaySchema(exclude=("id",))
gateway_list_schema = GatewaySchema(many=True, only=("name", "peripherals", "_links"))

peripheral_schema = PeripheralSchema(exclude=("id",))
peripherals_list_schema = PeripheralSchema(many=True, only=("vendor", "status", "_links", 'gateway'))


# Views
@app.route('/api/gateways', methods=['GET'])
def list_gateways():
    gateway_list = Gateway.query.all()
    return jsonify(gateway_list_schema.dump(gateway_list)), 200


@app.route("/api/gateways/<id>", methods=['GET'])
def gateway_detail(id):
    gateway = Gateway.query.get(id)
    if gateway is None:
        return '', 404
    return jsonify(gateway_schema.dump(gateway))


@app.route('/api/gateways', methods=['POST'])
def add_gateway():
    try:
        gateway = gateway_schema.load(request.get_json(force=True))
    except ValidationError as err:
        return jsonify(err.messages), 400
    db.session.add(gateway)
    db.session.commit()
    return gateway_schema.dump(gateway), 201


@app.route('/api/peripherals', methods=['GET'])
def list_peripheral():
    peripheral_list = Peripheral.query.all()
    return jsonify(peripherals_list_schema.dump(peripheral_list)), 200


@app.route("/api/peripherals/<id>", methods=['GET'])
def peripheral_detail(id):
    peripheral = Peripheral.query.get(id)
    if peripheral is None:
        return '', 404
    return jsonify(peripheral_schema.dump(peripheral))


@app.route('/api/peripherals', methods=['POST'])
def add_peripheral():
    try:
        peripheral = peripheral_schema.load(request.get_json(force=True))
    except ValidationError as err:
        return jsonify(err.messages), 400
    db.session.add(peripheral)
    db.session.commit()
    return peripheral_schema.dump(peripheral), 201


@app.route("/api/peripherals/<id>", methods=['DELETE'])
def remove_peripheral(id):
    peripheral = Peripheral.query.get(id)
    if peripheral is None:
        return '', 404
    db.session.delete(peripheral)
    db.session.commit()
    return '', 204


def main(argv):
    parser = argparse.ArgumentParser(description='Run flask gateway service.')
    parser.add_argument("-a", "--action", required=True, help="action to execute")
    parser.add_argument("-i", "--ip", default="127.0.0.1", help="ip address")
    args = vars(parser.parse_args())

    if args['action'] == "run":
        app.run(debug=True, host=args['ip'])
    elif args['action'] == "createdb":
        db.create_all()
    else:
        print("action: run|createdb")


if __name__ == '__main__':
    main(sys.argv[1:])
