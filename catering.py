import os
from datetime import date

from flask import Flask, request, session, redirect, url_for, render_template, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Date, ForeignKey, UniqueConstraint

#thanks stackoverflow!
class Base(DeclarativeBase):
    pass

app = Flask(__name__)
app.secret_key = "4" #i should use this for an intermediate CA private key too (please get the reference)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(app.root_path, "catering.db")

db = SQLAlchemy(model_class=Base)
db.init_app(app)

# everyone uses the same table, their role determines what they can do
class User(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))

    def __init__(self, username, password, role):
        self.username = username
        self.password = password
        self.role = role

# only one event can be booked per day
class Event(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("user.id"))

    customer: Mapped["User"] = relationship()
    signups: Mapped[list["Signup"]] = relationship(back_populates="event", cascade="all, delete-orphan")

    def __init__(self, date, customer_id):
        self.date = date
        self.customer_id = customer_id

# separate table to keep track of which staff members are working each event
class Signup(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("event.id"))
    staff_id: Mapped[int] = mapped_column(ForeignKey("user.id"))

    event: Mapped["Event"] = relationship(back_populates="signups")
    staff: Mapped["User"] = relationship()

    # prevent staff from signing up for the same event twice
    __table_args__ = (UniqueConstraint("event_id", "staff_id"),)

    def __init__(self, event_id, staff_id):
        self.event_id = event_id
        self.staff_id = staff_id

@app.cli.command("initdb")
def initdb_command():
    db.create_all()
    print("Initialized db")

@app.route("/")
def index():
    return redirect(url_for("login_controller"))

@app.route("/login/", methods=["GET", "POST"])
def login_controller():
    if "username" in session:
        return redirect(url_for("profile"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == "owner" and password == "pass": # owner account is defined in readme
            session["username"] = "owner"
            session["role"] = "owner"
            return redirect(url_for("profile"))

        user = User.query.filter_by(username=username).first()
        if user is not None and user.password == password:
            session["username"] = user.username
            session["role"] = user.role
            return redirect(url_for("profile"))

        flash("Incorrect username or password!")

    return render_template("login.html")

@app.route("/logout/")
def logout():
    session.clear()
    return redirect(url_for("login_controller"))


@app.route("/register/", methods=["GET", "POST"])
def register():
    if "username" in session:
        return redirect(url_for("profile"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Please enter a username and password!")
        elif username == "owner" or User.query.filter_by(username=username).first():
            flash("That username is already taken!")
        else:
            user = User(username, password, "customer")
            db.session.add(user)
            db.session.commit()
            flash("Account created, please log in!")
            return redirect(url_for("login_controller"))

    return render_template("register.html")


@app.route("/profile/")
@app.route("/profile/<username>")
def profile(username=None):
    if "username" not in session:
        return redirect(url_for("login_controller"))

    if session.get("role") == "owner":
        events = Event.query.order_by(Event.date).all()
        return render_template("owner.html", events=events)

    user = User.query.filter_by(username=session["username"]).first()
    if user is None:
        session.clear()
        return redirect(url_for("login_controller"))

    if user.role == "staff":
        events = Event.query.order_by(Event.date).all()
        working = []
        available = []

        # separate events staff member is already working from ones with open spots
        for event in events:
            signed_up = False
            for signup in event.signups:
                if signup.staff_id == user.id:
                    signed_up = True

            if signed_up:
                working.append(event)
            elif len(event.signups) < 3:
                available.append(event)

        return render_template("staff.html", working=working, available=available)

    events = Event.query.filter_by(customer_id=user.id).order_by(Event.date).all()
    return render_template("customer.html", events=events)


@app.route("/staff/create/", methods=["GET", "POST"])
def create_staff():
    if session.get("role") != "owner":
        return redirect(url_for("login_controller"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Please enter a username and password.")
        elif username == "owner" or User.query.filter_by(username=username).first():
            flash("That username is already taken.")
        else:
            staff = User(username, password, "staff")
            db.session.add(staff)
            db.session.commit()
            flash("Staff account created.")
            return redirect(url_for("profile"))

    return render_template("create_staff.html")


@app.route("/events/request/", methods=["POST"])
def request_event():
    if session.get("role") != "customer":
        return redirect(url_for("login_controller"))

    user = User.query.filter_by(username=session["username"], role="customer").first()
    if user is None:
        session.clear()
        return redirect(url_for("login_controller"))

    try:
        event_date = date.fromisoformat(request.form.get("date", ""))
    except ValueError:
        flash("Please choose a valid date.")
        return redirect(url_for("profile"))

    if Event.query.filter_by(date=event_date).first():
        flash("The company is already booked for that date!")
    else:
        event = Event(event_date, user.id)
        db.session.add(event)
        db.session.commit()
        flash("Event requested.")

    return redirect(url_for("profile"))

@app.route("/events/<int:event_id>/cancel/", methods=["POST"])
def cancel_event(event_id):
    #pycharm suggested "inverting the if statement"
    if session.get("role") == "customer":
        user = User.query.filter_by(username=session["username"], role="customer").first()
        if user is None:
            session.clear()
            return redirect(url_for("login_controller"))

        event = db.session.get(Event, event_id)
        if event is not None and event.customer_id == user.id:
            db.session.delete(event)
            db.session.commit()
            flash("Event canceled!")
        else:
            flash("You cannot cancel that event!")

        return redirect(url_for("profile"))

    return redirect(url_for("login_controller"))


@app.route("/events/<int:event_id>/signup/", methods=["POST"])
def sign_up(event_id):
    if session.get("role") != "staff":
        return redirect(url_for("login_controller"))

    user = User.query.filter_by(username=session["username"], role="staff").first()
    if user is None:
        session.clear()
        return redirect(url_for("login_controller"))

    event = db.session.get(Event, event_id)
    if event is None:
        flash("Event not found!")
    elif Signup.query.filter_by(event_id=event_id, staff_id=user.id).first():
        flash("You are already working this event!")
    elif len(event.signups) >= 3:
        flash("This event already has 3 staff members!")
    else:
        signup = Signup(event.id, user.id)
        db.session.add(signup)
        db.session.commit()
        flash("You signed up to work this event!")

    return redirect(url_for("profile"))
