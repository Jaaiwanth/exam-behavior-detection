import cv2
import os
import time
BASE_DIR = "dataset"
BEHAVIORS = {
    "1": ("normal", "looking_at_screen"),
    "2": ("normal", "looking_down"),
    "3": ("movements", "yawning"),
    "4": ("movements", "eye_rubbing"),
    "5": ("movements", "scratching_face"),
    "6": ("movements", "adjusting_glasses"),
    "7": ("movements", "drinking_water"),
    "8": ("suspicious", "repeated_left"),
    "9": ("suspicious", "repeated_right"),
    "10": ("suspicious", "looking_behind"),
    "11": ("suspicious", "prolonged_away"),
}

for category, behavior in BEHAVIORS.values():
    path = os.path.join(BASE_DIR, category, behavior)
    os.makedirs(path, exist_ok=True)

def get_next_filename(folder, behavior):
    existing_files = [
        f for f in os.listdir(folder)
        if f.startswith(behavior) and f.endswith(".mp4")
    ]

    numbers = []

    for file in existing_files:
        try:
            number = int(file.split("_")[-1].split(".")[0])
            numbers.append(number)
        except ValueError:
            pass

    next_number = max(numbers, default=0) + 1

    return os.path.join(
        folder,
        f"{behavior}_{next_number:03d}.mp4"
    )

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Could not open webcam.")
    exit()

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

print("\n===================================")
print("     STUDENT BEHAVIOR DATASET")
print("===================================\n")

print("Choose a behavior:\n")

for key, (_, behavior) in BEHAVIORS.items():
    print(f"{key:>2}. {behavior}")

print("\nQ = Quit")

choice = input("\nEnter choice: ").strip()

if choice.lower() == "q":
    cap.release()
    exit()

if choice not in BEHAVIORS:
    print("Invalid choice.")
    cap.release()
    exit()

category, behavior = BEHAVIORS[choice]

folder = os.path.join(BASE_DIR, category, behavior)

filename = get_next_filename(folder, behavior)

print(f"\nSelected: {behavior}")
print("Press ENTER in this terminal when you're ready.")
input()

# -----------------------------
# RECORDING SETTINGS
# -----------------------------

FPS = 20
DURATION = 5

width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

fourcc = cv2.VideoWriter_fourcc(*"mp4v")

writer = cv2.VideoWriter(
    filename,
    fourcc,
    FPS,
    (width, height)
)

print("\nRecording in:")

for i in range(3, 0, -1):

    print(i)

    start = time.time()

    while time.time() - start < 1:
        ret, frame = cap.read()

        if not ret:
            continue

        cv2.putText(
            frame,
            f"Starting in {i}",
            (50, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            2,
            (0, 0, 255),
            3
        )

        cv2.imshow("Dataset Collector", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            writer.release()
            cap.release()
            cv2.destroyAllWindows()
            exit()

print("RECORDING")

start_time = time.time()

while time.time() - start_time < DURATION:

    ret, frame = cap.read()

    if not ret:
        continue

    writer.write(frame)

    elapsed = time.time() - start_time
    remaining = DURATION - elapsed

    cv2.putText(
        frame,
        "RECORDING",
        (30, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 0, 255),
        2
    )

    cv2.putText(
        frame,
        f"{remaining:.1f}s",
        (30, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (255, 255, 255),
        2
    )

    cv2.imshow("Dataset Collector", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

writer.release()
cap.release()
cv2.destroyAllWindows()

print(f"\nSaved:")
print(filename)