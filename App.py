import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

from Create_Schedule import fetch_data
from Create_Schedule import main as create_schedule


config_path = Path.cwd() / "config.json"

with config_path.open("r", encoding="utf-8") as file:
    config = json.load(file)


root = tk.Tk()
root.title("Planning Center Scheduler")
root.geometry("700x600")


fields = [
    ("Application ID", "APP_ID"),
    ("Secret", "SECRET"),
    ("Period Start", "PERIOD_START"),
    ("Period End", "PERIOD_END"),
    ("Priority Penalty", "priority_penalty"),
    ("Preference Penalty", "preference_violation_penalty"),
    ("Overuse Penalty", "OVERUSE_PENALTY"),
    ("Repeated Use Penalty", "REPEATED_USE_PENALTY"),
    ("Rest Period", "rest_period"),
    ("Team-Specific Penalty (1=yes, 0=no)", "team_specific_penalty"),
]

fetch_setting_keys = {
    "APP_ID",
    "SECRET",
    "PERIOD_START",
    "PERIOD_END",
}

setting_variables = {}
setting_entries = {}

for row, (label_text, config_key) in enumerate(fields):
    tk.Label(root, text=label_text).grid(
        row=row,
        column=0,
        sticky="w",
        padx=5,
        pady=3,
    )

    variable = tk.StringVar(value=config.get(config_key, ""))
    setting_variables[config_key] = variable

    entry = tk.Entry(
        root,
        textvariable=variable,
        show="*" if config_key == "SECRET" else "",
    )
    entry.grid(
        row=row,
        column=1,
        columnspan=2,
        sticky="ew",
        padx=5,
        pady=3,
    )

    if config_key not in fetch_setting_keys:
        entry.configure(state="disabled")

    setting_entries[config_key] = entry


team_file = tk.StringVar(
    value=config.get("Updated_Teams_List", "")
)


def choose_team_file():
    selected_file = filedialog.askopenfilename(
        filetypes=[
            ("Excel files", "*.xlsx"),
            ("CSV files", "*.csv"),
        ]
    )

    if selected_file:
        team_file.set(selected_file)


next_row = len(fields)

tk.Label(root, text="Teams Spreadsheet").grid(
    row=next_row,
    column=0,
    sticky="w",
    padx=5,
    pady=3,
)

tk.Entry(root, textvariable=team_file).grid(
    row=next_row,
    column=1,
    sticky="ew",
    padx=5,
    pady=3,
)

tk.Button(
    root,
    text="Choose File",
    command=choose_team_file,
).grid(
    row=next_row,
    column=2,
    padx=5,
    pady=3,
)


weekly_slot_variables = []

for slot in config["weekly_slots"]:
    weekly_slot_variables.append({
        "position": tk.StringVar(value=slot["position"]),
        "position_id": tk.StringVar(value=slot["position_id"]),
        "missing_penalty": tk.StringVar(
            value=slot["missing_penalty"]
        ),
        "position_stress": tk.StringVar(
            value=slot["position_stress"]
        ),
        "hardship_factor": tk.StringVar(
            value=slot.get("hardship_factor", 1)
        ),
    })


def open_weekly_slot_editor():
    editor = tk.Toplevel(root)
    editor.title("Edit Weekly Slots")

    columns = [
        ("Position", "position", 25),
        ("Position ID", "position_id", 18),
        ("Missing Penalty", "missing_penalty", 12),
        ("Stress", "position_stress", 8),
        ("Hardship", "hardship_factor", 8),
    ]

    for column_number, (heading, _, _) in enumerate(columns):
        tk.Label(editor, text=heading).grid(
            row=0,
            column=column_number,
            padx=3,
            pady=3,
        )

    for row_number, slot_variables in enumerate(
        weekly_slot_variables,
        start=1,
    ):
        for column_number, (_, key, width) in enumerate(columns):
            tk.Entry(
                editor,
                textvariable=slot_variables[key],
                width=width,
            ).grid(
                row=row_number,
                column=column_number,
                padx=3,
                pady=2,
            )

    tk.Button(
        editor,
        text="Done",
        command=editor.destroy,
    ).grid(
        row=len(weekly_slot_variables) + 1,
        column=0,
        columnspan=len(columns),
        pady=8,
    )


def collect_config():
    updated_config = config.copy()

    for key, variable in setting_variables.items():
        updated_config[key] = variable.get()

    updated_config["Updated_Teams_List"] = team_file.get()

    integer_settings = [
        "priority_penalty",
        "preference_violation_penalty",
        "OVERUSE_PENALTY",
        "REPEATED_USE_PENALTY",
        "rest_period",
        "team_specific_penalty",
    ]

    for key in integer_settings:
        updated_config[key] = int(updated_config[key])

    updated_config["weekly_slots"] = []

    for slot_variables in weekly_slot_variables:
        updated_config["weekly_slots"].append({
            "position": slot_variables["position"].get(),
            "position_id": slot_variables["position_id"].get(),
            "missing_penalty": int(
                slot_variables["missing_penalty"].get()
            ),
            "position_stress": float(
                slot_variables["position_stress"].get()
            ),
            "hardship_factor": float(
                slot_variables["hardship_factor"].get()
            ),
        })

    return updated_config


planning_center_data = None
schedule_df = None
schedule_score = None


def export_schedule():
    selected_path = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV files", "*.csv")],
    )

    if selected_path:
        schedule_df.to_csv(selected_path)


def show_schedule_preview():
    preview_window = tk.Toplevel(root)
    preview_window.title("Schedule Preview")
    preview_window.geometry("900x600")

    summary_df = (
        schedule_df.stack()
        .rename("volunteer_name")
        .reset_index()
        [["volunteer_name", "position_id"]]
        .value_counts()
        .rename("count")
        .reset_index()
        .sort_values(by="volunteer_name")
    )

    tk.Label(
        preview_window,
        text=f"Score: {schedule_score:.2f}",
    ).pack(pady=5)

    preview_text = ScrolledText(
        preview_window,
        wrap="none",
    )
    preview_text.pack(fill="both", expand=True)

    horizontal_scrollbar = tk.Scrollbar(
        preview_window,
        orient="horizontal",
        command=preview_text.xview,
    )
    horizontal_scrollbar.pack(fill="x")

    preview_text.configure(
        xscrollcommand=horizontal_scrollbar.set
    )

    preview_text.insert(
        "1.0",
        "SCHEDULE\n\n"
        + schedule_df.to_string()
        + "\n\nVOLUNTEER SUMMARY\n\n"
        + summary_df.to_string(index=False),
    )
    preview_text.configure(state="disabled")

    tk.Button(
        preview_window,
        text="Export CSV",
        command=export_schedule,
    ).pack(pady=8)


def start_fetch():
    fetch_config = {
        "APP_ID": setting_variables["APP_ID"].get(),
        "SECRET": setting_variables["SECRET"].get(),
        "PERIOD_START": setting_variables["PERIOD_START"].get(),
        "PERIOD_END": setting_variables["PERIOD_END"].get(),
        "Updated_Teams_List": team_file.get(),
    }

    fetch_button.configure(state="disabled")
    generate_button.configure(state="disabled")
    edit_slots_button.configure(state="disabled")
    status_variable.set("Fetching Planning Center data...")

    worker = threading.Thread(
        target=run_fetch,
        args=(fetch_config,),
        daemon=True,
    )
    worker.start()


def run_fetch(fetch_config):
    try:
        result = fetch_data(fetch_config)
        root.after(0, fetch_finished, result)
    except Exception as error:
        root.after(0, fetch_failed, error)


def fetch_finished(result):
    global planning_center_data

    planning_center_data = result

    for key, entry in setting_entries.items():
        if key not in fetch_setting_keys:
            entry.configure(state="normal")

    fetch_button.configure(state="normal")
    generate_button.configure(state="normal")
    edit_slots_button.configure(state="normal")
    status_variable.set("Data fetched — configure schedule")


def fetch_failed(error):
    fetch_button.configure(state="normal")
    status_variable.set("Data fetch failed")
    messagebox.showerror("Error", str(error))


def start_generation():
    if planning_center_data is None:
        messagebox.showerror(
            "Error",
            "Fetch Planning Center data first.",
        )
        return

    try:
        updated_config = collect_config()

        with config_path.open("w", encoding="utf-8") as file:
            json.dump(updated_config, file, indent=2)

    except Exception as error:
        messagebox.showerror("Error", str(error))
        return

    generate_button.configure(state="disabled")
    status_variable.set("Generating schedule...")

    worker = threading.Thread(
        target=run_generation,
        args=(updated_config,),
        daemon=True,
    )
    worker.start()


def run_generation(updated_config):
    try:
        result = create_schedule(
            updated_config,
            planning_center_data,
        )
        root.after(0, generation_finished, result)
    except Exception as error:
        root.after(0, generation_failed, error)


def generation_finished(result):
    global schedule_df, schedule_score

    schedule_df, schedule_score = result

    generate_button.configure(state="normal")
    status_variable.set("Schedule complete")
    show_schedule_preview()


def generation_failed(error):
    generate_button.configure(state="normal")
    status_variable.set("Generation failed")
    messagebox.showerror("Error", str(error))


status_variable = tk.StringVar(value="Fetch data to begin")

fetch_button = tk.Button(
    root,
    text="Fetch Planning Center Data",
    command=start_fetch,
)
fetch_button.grid(
    row=next_row + 1,
    column=1,
    padx=5,
    pady=8,
)

edit_slots_button = tk.Button(
    root,
    text="Edit Weekly Slots",
    command=open_weekly_slot_editor,
    state="disabled",
)
edit_slots_button.grid(
    row=next_row + 2,
    column=1,
    padx=5,
    pady=8,
)

generate_button = tk.Button(
    root,
    text="Generate Schedule",
    command=start_generation,
    state="disabled",
)
generate_button.grid(
    row=next_row + 3,
    column=1,
    padx=5,
    pady=8,
)

tk.Label(
    root,
    textvariable=status_variable,
).grid(
    row=next_row + 4,
    column=1,
    padx=5,
    pady=3,
)

root.columnconfigure(1, weight=1)
root.mainloop()
