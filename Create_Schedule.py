import os
import json
import datetime
import pandas as pd
from pathlib import Path
from Planning_Center_Functions import *
from Schedule_Functions import *
from requests.auth import HTTPBasicAuth
from ortools.sat.python import cp_model
import ortools


config_path = Path.cwd()/"config.json"

with config_path.open("r", encoding="utf-8") as file:
    config = json.load(file)

# Read out config file contents
APP_ID = config['APP_ID']
SECRET = config['SECRET']
weekly_slots = config['weekly_slots']
auth = HTTPBasicAuth(APP_ID, SECRET)

PERIOD_START = datetime.datetime.fromisoformat(config['PERIOD_START']).date()
PERIOD_END = datetime.datetime.fromisoformat(config['PERIOD_END']).date()

active_teams_list = pd.read_excel(config['Updated_Teams_List']) 
# END CONFIG READOUT








def main():
	# First get lookup dictionaries between person, blockout, priority and full position
	model = cp_model.CpModel()

	# Create all datastructures necessary for creation
	all_sundays_list = pd.date_range(start=PERIOD_START, end=PERIOD_END, freq='W-SUN').date.tolist()

	BLOCKED_DATE_2_VOLUNTEER, TEAM_2_VOLUNTEER_DICT, VOLUNTEER_BLOCKOUTS, PRIORITY, PREFERENCES = create_dictionaries(auth, active_teams_list, PERIOD_START,PERIOD_END)

	schedule_problem = PCScheduler(model,
								weekly_slots,
								PERIOD_START,
								PERIOD_END,
								BLOCKED_DATE_2_VOLUNTEER,
								TEAM_2_VOLUNTEER_DICT,
								VOLUNTEER_BLOCKOUTS,
								PRIORITY,
								PREFERENCES)

	# Create all the data structures
	schedule_problem.create_all_position_slots_per_week()
	schedule_problem.create_dictionaries()
	schedule_problem.create_variables_space()
	
	# Add linear constraints to disallow duplicate scheduling
	schedule_problem.add_single_slot_constraint()
	schedule_problem.add_single_day_constraint()
	schedule_problem.add_preferences_constraints()

	# Set up structure to penalize empty slots, overworking, and pigeonholing
	schedule_problem.calc_empty_penalties()
	schedule_problem.calc_overworked_penalties()

	# User should choose team-based or general penalty

	schedule_problem.team_based_scheduling_penalty()
	# schedule_problem.general_scheduling_penalty()

	schedule_problem.solve_board()
	schedule_problem.output_results()

if __name__ == '__main__':
	main()