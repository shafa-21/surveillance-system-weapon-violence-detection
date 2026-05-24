import cv2
import numpy as np
import datetime
import os
import time
import pygame

from collections import deque
from ultralytics import YOLO
from tensorflow.keras.models import load_model

from django.shortcuts import render, redirect
from django.http import StreamingHttpResponse, JsonResponse
from django.conf import settings
from django.core.files import File

from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .models import Event


pygame.mixer.init()

alarm_path = os.path.join(settings.BASE_DIR, "alert.mp3")
alarm_sound = pygame.mixer.Sound(alarm_path)
alarm_channel = pygame.mixer.Channel(0)


IMG_SIZE = 96
SEQUENCE_LENGTH = 40
CONF_THRESHOLD = 0.5
VIDEO_SECONDS = 15
FPS = 20
EVENT_COOLDOWN = 5


weapon_model = YOLO(
    r"D:\Projects\cctv\cctv_webapp\weapon_detection\best.pt"
)

violence_model = load_model(
    r"D:\Projects\cctv\cctv_webapp\violence_detection\best_violence_model.keras"
)

frames = deque(maxlen=SEQUENCE_LENGTH)

recording = False
video_frames = []
event_type = ""
screenshot = None

alert_status_flag = False
last_event_time = 0
record_start_time = 0


# ---------------- AUTH ---------------- #

def login_view(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]

        user = authenticate(request, username=username, password=password)

        if user:
            login(request, user)
            return redirect("home")
        return render(request, "login.html", {"error": "Invalid credentials"})

    return render(request, "login.html")


def signup_view(request):
    if request.method == "POST":
        username = request.POST["username"]
        email = request.POST["email"]
        password = request.POST["password"]

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists")
            return redirect("signup")

        User.objects.create_user(username=username, email=email, password=password)
        messages.success(request, "Account created successfully")
        return redirect("login")

    return render(request, "signup.html")


def logout_view(request):
    logout(request)
    return redirect("login")


# ---------------- PAGES ---------------- #

@login_required
def home(request):
    weapon_count = Event.objects.filter(user=request.user, event_type="weapon").count()
    violence_count = Event.objects.filter(user=request.user, event_type="violence").count()
    total_events = Event.objects.filter(user=request.user).count()

    return render(request, "home.html", {
        "weapon_count": weapon_count,
        "violence_count": violence_count,
        "total_events": total_events
    })


@login_required
def live(request):
    return render(request, "live.html")


@login_required
def events(request):
    data = Event.objects.filter(user=request.user)

    search = request.GET.get("search")
    event_type = request.GET.get("type")
    date = request.GET.get("date")

    if search:
        data = data.filter(event_type__icontains=search)

    if event_type:
        data = data.filter(event_type=event_type)

    if date:
        data = data.filter(time__date=date)

    return render(request, "events.html", {"events": data.order_by("-time")})


@login_required
def delete_event(request, id):
    event = Event.objects.get(id=id, user=request.user)

    if event.screenshot and os.path.exists(event.screenshot.path):
        os.remove(event.screenshot.path)

    if event.video and os.path.exists(event.video.path):
        os.remove(event.video.path)

    event.delete()
    return redirect("events")


@login_required
def alert_status_view(request):
    return JsonResponse({"alert": alert_status_flag})


# ---------------- STREAM CORE ---------------- #

def generate_frames(user):
    global recording, video_frames, event_type, screenshot
    global alert_status_flag, last_event_time, record_start_time

    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Camera not accessible")
        return

    while True:
        success, frame = cap.read()
        if not success:
            continue

        annotated = frame.copy()

        weapon_detected = False
        violence_detected = False

        # -------- Weapon Detection -------- #
        results = weapon_model(frame, conf=CONF_THRESHOLD, verbose=False)

        if results and len(results[0].boxes) > 0:
            weapon_detected = True
            for box in results[0].boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)

        # -------- Violence Detection -------- #
        img = cv2.resize(frame, (IMG_SIZE, IMG_SIZE)) / 255.0
        frames.append(img)

        if len(frames) == SEQUENCE_LENGTH:
            input_data = np.expand_dims(np.array(frames), axis=0)
            pred = violence_model.predict(input_data, verbose=0)

            if pred[0][0] > 0.5:
                violence_detected = True

        # -------- ALERT TEXT -------- #
        if weapon_detected:
            cv2.putText(annotated, "WEAPON DETECTED", (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        if violence_detected:
            cv2.putText(annotated, "VIOLENCE DETECTED", (30, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        # -------- ALERT SOUND -------- #
        if weapon_detected or violence_detected:
            alert_status_flag = True
            if not alarm_channel.get_busy():
                alarm_channel.play(alarm_sound)
        else:
            alert_status_flag = False
            if alarm_channel.get_busy():
                alarm_channel.stop()

        # -------- EVENT RECORDING -------- #
        current_time = time.time()
        trigger = weapon_detected or violence_detected

        if trigger and not recording and current_time - last_event_time > EVENT_COOLDOWN:
            recording = True
            video_frames = []
            screenshot = frame.copy()
            event_type = "weapon" if weapon_detected else "violence"
            record_start_time = current_time
            last_event_time = current_time

        if recording:
            video_frames.append(annotated.copy())

            if time.time() - record_start_time >= VIDEO_SECONDS:

                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

                screenshot_dir = os.path.join(settings.MEDIA_ROOT, "screenshots")
                video_dir = os.path.join(settings.MEDIA_ROOT, "videos")

                os.makedirs(screenshot_dir, exist_ok=True)
                os.makedirs(video_dir, exist_ok=True)

                img_name = f"{timestamp}.jpg"
                vid_name = f"{timestamp}.mp4"

                screenshot_path = os.path.join(screenshot_dir, img_name)
                video_path = os.path.join(video_dir, vid_name)

                cv2.imwrite(screenshot_path, screenshot)

                h, w, _ = frame.shape
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                out = cv2.VideoWriter(video_path, fourcc, FPS, (w, h))

                for f in video_frames:
                    out.write(f)

                out.release()

                event = Event(user=user, event_type=event_type)

                with open(screenshot_path, "rb") as img_file:
                    event.screenshot.save(img_name, File(img_file), save=False)

                with open(video_path, "rb") as vid_file:
                    event.video.save(vid_name, File(vid_file), save=False)

                event.save()

                recording = False
                video_frames = []

        # -------- STREAM FRAME -------- #
        ret, buffer = cv2.imencode(".jpg", annotated)
        frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

    cap.release()


# ---------------- VIDEO FEED ---------------- #

@login_required
def video_feed(request):
    response = StreamingHttpResponse(
        generate_frames(request.user),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )

    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'

    return response