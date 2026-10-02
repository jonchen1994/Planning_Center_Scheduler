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

def fetch_data(config):
    auth = HTTPBasicAuth(
        config["APP_ID"],
        config["SECRET"],
    )

    period_start = datetime.datetime.fromisoformat(config['PERIOD_START']).date()

    period_end = datetime.datetime.fromisoformat(config['PERIOD_END']).date()

    input_path = Path(config["Updated_Teams_List"])

    if input_path.suffix.lower() == ".csv":
        active_teams_list = pd.read_csv(input_path)
    else:
        active_teams_list = pd.read_excel(input_path)

    return create_dictionaries(
        auth,
        active_teams_list,
        period_start,
        period_end,
    )


def main(config, planning_center_data):

	(BLOCKED_DATE_2_VOLUNTEER,TEAM_2_VOLUNTEER_DICT,VOLUNTEER_BLOCKOUTS,PRIORITY,PREFERENCES) = planning_center_data

	PERIOD_START = datetime.datetime.fromisoformat(config['PERIOD_START']).date()
	PERIOD_END = datetime.datetime.fromisoformat(config['PERIOD_END']).date()
	weekly_slots = config["weekly_slots"]

	# First get lookup dictionaries between person, blockout, priority and full position
	model = cp_model.CpModel()

	# Create all datastructures necessary for creation
	all_sundays_list = pd.date_range(start=PERIOD_START, end=PERIOD_END, freq='W-SUN').date.tolist()

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
	schedule_problem.create_variables_space(priority_penalty=config["priority_penalty"])
	
	# Add linear constraints to disallow duplicate scheduling
	schedule_problem.add_single_slot_constraint()
	schedule_problem.add_single_day_constraint()
	schedule_problem.add_preferences_constraints(preference_violation_penalty=config["preference_violation_penalty"])

	# Set up structure to penalize empty slots, overworking, and pigeonholing
	schedule_problem.calc_empty_penalties()
	schedule_problem.calc_overworked_penalties(OVERUSE_PENALTY=config["OVERUSE_PENALTY"], rest_period=config["rest_period"])

	# User should choose team-based or general penalty
	if config["team_specific_penalty"] == 1:
		schedule_problem.team_based_scheduling_penalty()
	else:
		schedule_problem.general_scheduling_penalty(config["REPEATED_USE_PENALTY"])

	schedule_problem.solve_board()
	schedule_df = schedule_problem.output_results()
	score = schedule_problem.solver.ObjectiveValue()

	return schedule_df, score

if __name__ == '__main__':

	config_path = Path.cwd()/"config.json"

	with config_path.open("r", encoding="utf-8") as file:
		config = json.load(file)

	schedule_df = main(config)
	schedule_df.to_csv("output.csv")