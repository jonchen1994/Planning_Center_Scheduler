import json
import pandas as pd
import ortools
from dataclasses import dataclass, field
import datetime
from ortools.sat.python import cp_model


class PCScheduler():

    def __init__(self, model, weekly_slots, PERIOD_START, PERIOD_END, BLOCKED_DATE_2_VOLUNTEER,TEAM_2_VOLUNTEER_DICT, VOLUNTEER_BLOCKOUTS, PRIORITY, PREFERENCES ):
        self.model = model
        self.BLOCKED_DATE_2_VOLUNTEER = BLOCKED_DATE_2_VOLUNTEER
        self.TEAM_2_VOLUNTEER_DICT = TEAM_2_VOLUNTEER_DICT
        self.VOLUNTEER_BLOCKOUTS = VOLUNTEER_BLOCKOUTS
        self.PRIORITY = PRIORITY
        self.PREFERENCES = PREFERENCES
        self.PERIOD_START = PERIOD_START
        self.PERIOD_END = PERIOD_END
        self.weekly_slots = weekly_slots
        self.sundays_list = pd.date_range(start=self.PERIOD_START, end=self.PERIOD_END, freq='W-SUN').date.tolist() 


    def create_all_position_slots_per_week(self):
        # Creates the entire matrix/board of slots that need volunteers and every sunday
        position_slots = []
        for index, sunday in enumerate(self.sundays_list):

            for slot in self.weekly_slots:
        
                new_slot = slot.copy()
                position_id = slot.get('position_id')
                position_name = slot.get('position')
                #Youth Leadeers meet every other
                if index % 2 == 0 and position_name == 'Youth Leaders':
                    continue 
                slot_id = f'{str(sunday)}_{position_id}'
                new_slot['slot_id'] = slot_id
                new_slot['date'] = sunday
                position_slots.append(new_slot)
         
        self.position_slots = position_slots
       
    def create_dictionaries(self):
        #create all lookup dictionaries from the Sunday slots list
        self.penalty_lookup = {w['slot_id'] : w['missing_penalty'] for w in self.position_slots} 
        self.stress_lookup = {w['slot_id'] : w['position_stress'] for w in self.position_slots}
        self.slot_to_day = {w['slot_id'] : w['date'] for w in self.position_slots} 
        self.id_to_name_lookup = {v['Person_ID']: v['Full_Name'] for v in self.VOLUNTEER_BLOCKOUTS}

        self.volunteer_list = [v['Person_ID'] for v in self.VOLUNTEER_BLOCKOUTS]

    def create_variables_space(self):
        x = {}
        penalties = []

        for position in self.position_slots:
            slot_id = position['slot_id']
            position_name = position['position']
            position_date = position['date']
            valid_volunteers = self.TEAM_2_VOLUNTEER_DICT[position_name]
            blocked_volunteers = self.BLOCKED_DATE_2_VOLUNTEER.get(
                position_date,
                set()
            )
            for volunteer in valid_volunteers:
                if volunteer in blocked_volunteers:
                    continue
        
                x[(slot_id, volunteer)] = self.model.NewBoolVar(f'{slot_id}_{volunteer}')
                penalties.append(x[(slot_id, volunteer)]*self.stress_lookup[slot_id])
        
                priority = self.PRIORITY.get((volunteer, position_name), 1)
                penalties.append(x[(slot_id, volunteer)]  * (priority - 1) * 20)

        self.x = x
        self.penalties = penalties

    def add_single_slot_constraint(self):
        for slot in self.position_slots:
            # you cannot have 2 persons working the same slot
            slot_id = slot['slot_id']
            position_name = slot['position']
            valid_persons = [p_id for s_id, p_id in self.x if slot_id == s_id]
            self.model.Add(
                sum(self.x[(slot_id, person_id)] for person_id in valid_persons) <= 1)


    def add_single_day_constraint(self):
        # you cannot have 1 person working two slots on the same day
        # while also looping through volunteers and dates, also contrain whether or not the person has worked on the date to the slots per day. 
        worked = {}
        for date in self.sundays_list:
            # get slots per day
            slot_ids_per_date = [p['slot_id'] for p in self.position_slots if p['date'] == date]
            for v in self.volunteer_list:

                worked[(v, date)] = self.model.NewBoolVar(f'worked_{v}_{date}')
        
                slots_per_vol_per_day = [self.x[(s,v)] for s in slot_ids_per_date if (s,v) in self.x]
                if slots_per_vol_per_day:
                    self.model.Add(sum(slots_per_vol_per_day) <= 1)
                    self.model.Add(worked[(v,date)] == sum(slots_per_vol_per_day))
                else:
                    self.model.Add(worked[(v,date)] == 0)

        self.worked = worked

    def add_preferences_constraints(self):
        # To implement preferences - I need to loop through the preferences and then each sunday

        worked_people = {
            person_id
            for person_id, date in self.worked
        }

        for i, p in enumerate(self.PREFERENCES):
            index = i
            origin_person = p['Person_ID']
            target_person = p['Target_ID']
            pref_type = p['preference']

            missing_people = {
                origin_person,
                target_person
            } - worked_people

            if missing_people:
                raise ValueError(
                    f"Preference references unknown people: {missing_people}"
                )

            for date in self.sundays_list:
                pref_violation = self.model.NewBoolVar(f'{origin_person}_{target_person}_preference')
        
                origin_person_worked = self.worked[(origin_person, date)]
                target_person_worked = self.worked[(target_person, date)]
        
                #Add constraints depending on preference style
                """
                NOTE - preferences aren't used very much currently and I don't think most people understand
                the difference between the options. For now just see if 'Don't' was in their selction
                """
                if "Don't" not in pref_type:
                    #This only goes one direction - this allows for more flexibility in Planning Center
                    # Violation occurs when one is assigned and the other has not
                    self.model.Add(pref_violation >= origin_person_worked - target_person_worked)
                    self.model.Add(pref_violation <= origin_person_worked)
                    self.model.Add(pref_violation <= 1 - target_person_worked)
                else:
                    # Only violation when both are working at the same time
                    self.model.Add(pref_violation >= origin_person_worked + target_person_worked - 1)
                    self.model.Add(pref_violation <= origin_person_worked)
                    self.model.Add(pref_violation <= target_person_worked)

        
                self.penalties.append(pref_violation*100)

    def calc_empty_penalties(self):
        ## create penalities list for empty positions

        # First create a list for all positions
        empty = {} 
        for slot in self.position_slots:
            slot_id = slot['slot_id']

            empty[slot_id] = self.model.NewBoolVar(f'empty_{slot_id}')

        for e in empty:
            all_possible_slots = [self.x[(e, p_id)] for s_id, p_id in self.x if s_id == e]
            self.model.Add(sum(all_possible_slots) + empty[e] == 1)
            self.penalties.append(empty[e]*self.penalty_lookup[e])

        self.empty = empty
    
    def calc_overworked_penalties(self, OVERUSE_PENALTY = 100, rest_period = 3):
        # create penalties when a volunteer has been worked over 'rest_period'
        # amount of times. Penalty scales linearly with amount overworked
        for v in self.volunteer_list:
            for i in range(len(self.sundays_list)-(rest_period-1)):
                temp_sundays = self.sundays_list[i:i+rest_period]
                d1 = temp_sundays[0]
                worked_count = sum([self.worked[(v,d)] for d in temp_sundays])

                #First one is free
                excess = self.model.NewIntVar(0, rest_period-1, f"excess_3wk_{v}_{d1}")

                self.model.Add(excess >= worked_count - 1)

                self.penalties.append(excess * OVERUSE_PENALTY)

    def general_scheduling_penalty(self, REPEATED_USE_PENALTY = 10):
        # Add very light penalities to encourage more spread out usage
        for v in self.volunteer_list:
            total_worked = sum([self.worked[(v,d)] for d in self.sundays_list])

            repetition = self.model.NewIntVar(0, len(self.sundays_list)-1, f"num_times_{v}_worked")

            self.model.Add(repetition >= total_worked-1)

            self.penalties.append(repetition * REPEATED_USE_PENALTY)

    def team_based_scheduling_penalty(self):
        # This adds penalties based on volunteering per team,
        # and encourages not pigeonholing someone into only 1 role
        for team, team_volunteers in self.TEAM_2_VOLUNTEER_DICT.items():
            # get all positions
            all_team_slots = [p['slot_id'] for p in self.position_slots if p['position']==team]
            # Repetition penalties for the same position should scale with the stress of the job
            team_stress_penalty = self.stress_lookup[all_team_slots[0]]/10
            # get the sum of each volunteer in each position
            for v in team_volunteers:
                all_vol_x_team_slots = [self.x[(s, v)] for s in all_team_slots if (s,v) in self.x]
                if not all_vol_x_team_slots:
                    continue
                team_repetition = self.model.NewIntVar(0, len(all_vol_x_team_slots)-1, f"num_{v}_in_{team}_role")
                self.model.Add(team_repetition >= sum(all_vol_x_team_slots) - 1)
                self.penalties.append(team_repetition * team_stress_penalty)


    def solve_board(self):
        self.model.minimize(sum(self.penalties))

        self.solver = cp_model.CpSolver()
        self.status = self.solver.Solve(self.model)

        if self.status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print("Score:", self.solver.ObjectiveValue())

            schedule = {}

            for (slot_id, volunteer_id), var in self.x.items():
                if self.solver.Value(var) == 1:
                    schedule[slot_id] = volunteer_id
        else:
            print("No solution found")

    def output_results(self):
        slots_by_id = {s["slot_id"]: s for s in self.position_slots}

        schedule_rows = []

        for (slot_id, volunteer_id), var in self.x.items():
            if self.solver.Value(var) == 1:
                slot = slots_by_id[slot_id]

                schedule_rows.append({
                    "date": slot["date"],
                    "position_id": slot["position_id"],
                    "slot_id": slot_id,
                    "volunteer_name": self.id_to_name_lookup[volunteer_id],
                })

        schedule_df = pd.DataFrame(schedule_rows).sort_values(["date", "position_id"])

        schedule_df.pivot_table(
            index="position_id",
            columns="date",
            values="volunteer_name",
            aggfunc="first"
        ).to_csv('output.csv')
