import pandas as pd
import numpy as np
import requests
import json
from pathlib import Path
from requests.auth import HTTPBasicAuth
from tqdm import tqdm
import datetime
from collections import defaultdict
import time
"""
config_path = Path.cwd()/"config.json"

with config_path.open("r", encoding="utf-8") as file:
    config = json.load(file)
"""
# use to determine if blockout dates from the API are indeed within the target period
def in_period(start_date, end_date, target_date):
    return (target_date >= start_date) and (target_date <= end_date)

def _get_all_from_url_nexts(url, auth):
    accumulated = []
    
    while url:
        response = requests.get(url,
                                auth = auth)
                                
        data =response.json()
        accumulated.extend(data.get('data'))
        url = data.get('links').get('next')
        time.sleep(.5)

    return accumulated


# Filter out all blockouts that aren't relevant to the staffing period
def _filter_blockouts(person_blockout_list, period_start, period_end): 
    all_blockouts = [] 
    for b in person_blockout_list: 
        data = b.get('attributes')
        end_date = datetime.datetime.strptime(
            data.get('ends_at'),
            '%Y-%m-%dT%H:%M:%SZ'
            ).date() 
        start_date = datetime.datetime.strptime(
            data.get('starts_at'),
            '%Y-%m-%dT%H:%M:%SZ'
            ).date() 
        if start_date <= period_end and end_date >= period_start:
            all_blockouts.append({
                "start_date": start_date,
                "end_date": end_date,
            })

    return all_blockouts

"""
auth: HTTPBasicAuth
active_teams_list: dataframe
"""
def _get_current_active_teams(auth, active_teams_list,):
    # read in the active_teams_list and clean it
    active_teams_list = active_teams_list.fillna('')
    active_teams_list['Full_Team'] = np.where(
        active_teams_list['Position'].ne(""),
        active_teams_list['Team_Name'] + '-' + active_teams_list['Position'],
        active_teams_list['Team_Name']
    ) 
    active_teams_list[['First_Name', 'Last_Name']] = active_teams_list['Full_Name'].str.split(" ", expand = True)
    people_data = _get_person_id_from_PC(auth)
    full_active_team_df = active_teams_list.merge(people_data, how = 'left', on=['First_Name', 'Last_Name']) 
    return full_active_team_df

# get all the people data from Planning Center
def _get_person_id_from_PC(auth):
    print('Getting volunteer data from Planning Center')
    people_data = _get_all_from_url_nexts('https://api.planningcenteronline.com/people/v2/people', auth) 
    people_data = pd.json_normalize(people_data)
    people_data = people_data[['id','attributes.first_name','attributes.last_name']]
    people_data.columns = ['Person_ID', 'First_Name', 'Last_Name'] 
    return people_data

# get all preferences for each person
def _get_person_preferences(auth, full_active_team_df):
    volunteer_preferences = []
    unique_vols = full_active_team_df[['Person_ID', 'Full_Name']].drop_duplicates()
    print('Getting scheduling preferences from Planning Center')
    for i, r in tqdm(unique_vols.iterrows(), total = len(unique_vols)): 
        vol_id = r['Person_ID']
        full_name = r['Full_Name']
        preference_url = f'https://api.planningcenteronline.com/services/v2/people/{vol_id}/scheduling_preferences'
        person_preferences = _get_all_from_url_nexts(preference_url, auth)
        if len(person_preferences) == 0:
            continue
        volunteer_preferences.append({
                "Person_ID": vol_id,
                "Full_Name": full_name,
                "preferences": person_preferences
            })
    
    # create a dictionary of preferences so later I can check if preferences are being met
    personal_preferences = []
    for v in volunteer_preferences:
    
        for p in v['preferences']:
            if p['attributes']['preference'] == 'No preference':
                continue
            personal_preferences.append({
                "Person_Name": v['Full_Name'],
                "Person_ID": v['Person_ID'],
                "Target_ID":p['relationships']['household_member']['data']['id'],
                "preference":p['attributes']['preference']
            })
        
    return personal_preferences

def _get_volunteer_blockouts(full_active_team_df, PERIOD_START, PERIOD_END, auth):
    sundays_list = pd.date_range(start=PERIOD_START, end=PERIOD_END, freq='W-SUN').date.tolist()
    # First get all blockouts from planning center
    unique_vols = full_active_team_df[['Person_ID', 'Full_Name']].drop_duplicates()
    volunteer_blockouts = []
    print('Getting Blockout dates from Planning Center')
    for i, r in tqdm(unique_vols.iterrows(), total = len(unique_vols)):
        vol_id = r['Person_ID']
        full_name = r['Full_Name']
        blockout_url = f'https://api.planningcenteronline.com/services/v2/people/{vol_id}/blockouts'
        person_blockouts = _get_all_from_url_nexts(blockout_url, auth) 
        person_blockouts = _filter_blockouts(person_blockouts, PERIOD_START, PERIOD_END)
        volunteer_blockouts.append({
                "Person_ID": vol_id,
                "Full_Name": full_name,
                "relevant_blockouts": person_blockouts
        })
    
     # next enrich the sets
    for v in volunteer_blockouts:
        blocks = v.get('relevant_blockouts')
        blocked_sundays = []
        for s in sundays_list:
            for b in blocks:
                if in_period(b['start_date'],b['end_date'], s):
                    blocked_sundays.append(s)
        v['blockouts'] = set(blocked_sundays) 

    for v in volunteer_blockouts:
        temp_name = v.get('Full_Name')
        subset = full_active_team_df[full_active_team_df['Full_Name'] == temp_name]
        if len(subset) == 0:
            print(f'{temp_name} not found in teamslist')
            v['positions'] = {}
        else:
            v['positions'] = set(subset['Full_Team'].tolist()) 

    return volunteer_blockouts

def create_dictionaries(auth, active_teams_list, PERIOD_START, PERIOD_END):
    all_sundays_list = pd.date_range(start=PERIOD_START, end=PERIOD_END, freq='W-SUN').date.tolist()
    full_active_team_df = _get_current_active_teams(auth, active_teams_list)
    teams = full_active_team_df[['Full_Team','Person_ID']].groupby('Full_Team').agg(list).reset_index() 

    # Create a dictionary between the Full Team Name/Role and the Person
    team_2_volunteer_dict = {}
    for t in teams.to_dict(orient = 'records'): 
        team_2_volunteer_dict[t['Full_Team']] = set(t['Person_ID'])
    
    team_2_volunteer_dict = dict(team_2_volunteer_dict)

    volunteer_blockouts = _get_volunteer_blockouts(full_active_team_df, PERIOD_START, PERIOD_END, auth)
    blocked_date_2_volunteer = defaultdict(set)

    # Create a dictionary between the Person and Blocked out date
    for v in volunteer_blockouts:
        name = v.get('Person_ID')

        for blockout_date in v.get('blockouts'):
            blocked_date_2_volunteer[blockout_date].add(name)

    
    blocked_date_2_volunteer = dict(blocked_date_2_volunteer)

    # Create a dictionary between the Person and priority
    position_priority = full_active_team_df[['Person_ID', 'Full_Team','Priority']].drop_duplicates() 
    person_priority_lookup = {
        (row['Person_ID'], row['Full_Team']): row['Priority']
        for i, row in position_priority.iterrows()
    }

    # get personal preferences
    personal_preferences = _get_person_preferences(auth, full_active_team_df)

    return blocked_date_2_volunteer, team_2_volunteer_dict, volunteer_blockouts, person_priority_lookup, personal_preferences