import pandas
import operator
import yaml
import os
import json
import time
import sys
import re

from internal.weights import find_weights
from internal.spell_ids import find_ids
from datetime import datetime

with open("config.yml", "r") as ymlfile:
    config = yaml.load(ymlfile, Loader=yaml.FullLoader)


def assure_path_exists(path):
    dir_name = os.path.dirname(path)
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)


def build_output_string(sim_type, talent_string, covenant_string, file_type):
    output_dir = "results/"
    assure_path_exists(output_dir)
    return "{0}Results_{1}{2}{3}.{4}".format(output_dir, sim_type, talent_string, covenant_string, file_type)


def get_change(current, previous):
    negative = 0
    if current < previous:
        negative = True
    try:
        value = (abs(current - previous) / previous) * 100.0
        value = float('%.2f' % value)
        if value >= 0.01 and negative:
            value = value * -1
        return value
    except ZeroDivisionError:
        return 0


def find_weight(sim_type, profile_name):
    weight_type = ""
    if sim_type == "Composite":
        weight_type = "compositeWeights"
    elif sim_type == "Single":
        weight_type = "singleTargetWeights"
    elif sim_type == "Dungeons":
        # Dungeon sim is just 1 sim, so we return 1 here
        return 1
    weight = find_weights(config[weight_type]).get(profile_name)
    if not weight:
        return 0
    else:
        return weight


def build_results(data, weights, sim_type, directory):
    results = {}
    for value in data.iterrows():
        profile = value[1].profile
        actor = value[1].actor
        fight_style = re.search('((hm|lm|pw).*|dungeons$)', profile).group()
        weight = find_weight(sim_type, fight_style)
        weighted_dps = value[1].DPS * weight
        if weights:
            intellect = value[1].int * weight
            haste = value[1].haste / intellect * weight
            crit = value[1].crit / intellect * weight
            mastery = value[1].mastery / intellect * weight
            vers = value[1].vers / intellect * weight
            wdps = 1 / intellect * weight
            weight = 1 * weight
            if actor in results:
                existing = results[actor]
                results[actor] = [existing[0] + weighted_dps, existing[1] + weight, existing[2] + haste,
                                  existing[3] + crit, existing[4] +
                                  mastery, existing[5] + vers,
                                  existing[6] + wdps]
            else:
                results[actor] = [weighted_dps, weight,
                                  haste, crit, mastery, vers, wdps]
        else:
            if actor in results:
                results[actor] = results[actor] + weighted_dps
            else:
                results[actor] = weighted_dps
    # Each profile sims "Base" again so we need to divide that to get the real average
    number_of_profiles = len(config["sims"][directory[:-1]]["files"])

    if config["sims"][directory[:-1]]["covenant"]["files"]:
        number_of_profiles = 1

    base_dps = results.get('Base') / number_of_profiles
    results['Base'] = base_dps
    return results


def generate_report_name(sim_type, talent_string, covenant_string):
    talents = " - {0}".format(talent_string.strip("_")
                              ) if talent_string else ""
    covenant = " - {0}".format(covenant_string.strip("_")
                               ) if covenant_string else ""
    return "{0}{1}{2}".format(sim_type, talents, covenant)


def build_markdown(sim_type, talent_string, results, weights, base_dps, covenant_string):
    output_file = build_output_string(
        sim_type, talent_string, covenant_string, "md")
    with open(output_file, 'w+') as results_md:
        if weights:
            results_md.write(
                '# {0}\n| Actor | DPS | Int | Haste | Crit | Mastery | Vers | DPS Weight '
                '|\n|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n'.format(generate_report_name(sim_type, talent_string, covenant_string)))
            for key, value in sorted(results.items(), key=operator.itemgetter(1), reverse=True):
                results_md.write("|%s|%.0f|%.2f|%.2f|%.2f|%.2f|%.2f|%.2f|\n" % (
                    key, value[0], value[1], value[2], value[3], value[4], value[5], value[6]))
        else:
            results_md.write('# {0}\n| Actor | DPS | Increase |\n|---|:---:|:---:|\n'.format(
                generate_report_name(sim_type, talent_string, covenant_string)))
            for key, value in sorted(results.items(), key=operator.itemgetter(1), reverse=True):
                results_md.write("|%s|%.0f|%.2f%%|\n" %
                                 (key, value, get_change(value, base_dps)))


def build_csv(sim_type, talent_string, results, weights, base_dps, covenant_string):
    output_file = build_output_string(
        sim_type, talent_string, covenant_string, "csv")
    with open(output_file, 'w') as results_csv:
        if weights:
            results_csv.write(
                'profile,actor,DPS,int,haste,crit,mastery,vers,dpsW,\n')
            for key, value in sorted(results.items(), key=operator.itemgetter(1), reverse=True):
                results_csv.write("%s,%s,%.0f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,\n" % (
                    sim_type, key, value[0], value[1], value[2], value[3], value[4], value[5], value[6]))
        else:
            results_csv.write('profile,actor,DPS,increase,\n')
            for key, value in sorted(results.items(), key=operator.itemgetter(1), reverse=True):
                results_csv.write("%s,%s,%.0f,%.2f%%,\n" % (
                    sim_type, key, value, get_change(value, base_dps)))


def lookup_id(name, directory):
    lookup_type = config["sims"][directory[:-1]]["lookupType"]
    if lookup_type == "spell":
        return lookup_spell_id(name, directory)
    elif lookup_type == "item":
        return lookup_item_id(name, directory)
    else:
        return None


def lookup_spell_id(spell_name, directory):
    ids = find_ids(directory[:-1])
    if ids:
        return ids.get(spell_name)
    else:
        return None


def lookup_item_id(item_name, directory):
    # get the list of sim files from config
    # loop over them and search for the item name line by line
    for sim_file in config["sims"][directory[:-1]]["files"]:
        with open(sim_file, 'r') as file:
            for line in file:
                if item_name in line:
                    # find ,id= -> take 2nd half ->
                    # find , -> take 1st half
                    return int(line.split(',id=')[1].split(',')[0])


def build_json(sim_type, talent_string, results, directory, timestamp, covenant_string):
    output_file = build_output_string(
        sim_type, talent_string, covenant_string, "json")
    human_date = time.strftime('%Y-%m-%d', time.localtime(timestamp))
    chart_data = {
        "name": generate_report_name(sim_type, talent_string, covenant_string),
        "data": {},
        "ids": {},
        "simulated_steps": [],
        "sorted_data_keys": [],
        "last_updated": human_date
    }
    # check steps in config
    # for each profile, try to find every step
    # if found put in unique dict
    steps = config["sims"][directory[:-1]]["steps"]
    number_of_steps = len(steps)

    # if there is only 1 step, we can just go right to iterating
    if number_of_steps == 1:
        chart_data["simulated_steps"] = ["DPS"]
        for key, value in sorted(results.items(), key=operator.itemgetter(1), reverse=True):
            chart_data["data"][key] = {
                "DPS": int(round(value, 0))
            }
            if key != "Base":
                chart_data["sorted_data_keys"].append(key)
                chart_data["ids"][key] = lookup_id(key, directory)
    else:
        unique_profiles = []
        chart_data["simulated_steps"] = steps
        # iterate over results and build a list of unique profiles
        # trim off everything after last _
        for key, value in results.items():
            unique_key = '_'.join(key.split('_')[:-1])
            if unique_key not in unique_profiles and unique_key != "Base" and unique_key != "":
                unique_profiles.append(unique_key)
                chart_data["sorted_data_keys"].append(unique_key)
                chart_data["ids"][unique_key] = lookup_id(
                    unique_key, directory)
        for profile in unique_profiles:
            chart_data["data"][profile] = {}
            steps.sort(reverse=True)
            # Make sure that the steps in the json are from highest to lowest
            for step in steps:
                for key, value in sorted(results.items(), key=operator.itemgetter(1), reverse=True):
                    # split off the key to get the step
                    # key: Trinket_415 would turn into 415
                    key_step = key.split('_')[len(key.split('_')) - 1]
                    if profile in key and str(key_step) == str(step):
                        chart_data["data"][profile][step] = int(
                            round(value, 0))
        # Base isn't in unique_profiles so we handle that explicitly
        chart_data["data"]["Base"] = {}
        chart_data["data"]["Base"]["DPS"] = int(round(results.get("Base"), 0))
    json_data = json.dumps(chart_data)
    with open(output_file, 'w') as results_json:
        results_json.write(json_data)


def convert_increase_to_double(increase):
    increase = increase.strip('%')
    increase = round(float(increase), 4)
    if increase:
        increase = round(increase / 100, 4)
    return increase


def build_talented_covenant_json(talents):
    sim_types = ["Composite", "Dungeons", "Single"]
    results = {}
    # find the 3 CSV files for the given talent setup
    for sim_type in sim_types:
        csv = "results/Results_{0}_{1}.csv".format(sim_type, talents)
        data = pandas.read_csv(
            csv, usecols=['profile', 'actor', 'DPS', 'increase'])
        covenants = {
            "kyrian": {"max": 0.00, "min": 0.00},
            "necrolord": {"max": 0.00, "min": 0.00},
            "night_fae": {"max": 0.00, "min": 0.00},
            "venthyr": {"max": 0.00, "min": 0.00},
            "base": {"DPS": 0.00}
        }
        # for each file, iterate over results to get max/min per covenant
        for value in data.iterrows():
            covenant = re.sub(r"_\d+", "", value[1].actor).lower()
            covenant_dict = covenants.get(covenant)
            if covenant == "base":
                covenants["base"]["DPS"] = convert_increase_to_double(
                    value[1].increase)
            elif covenant_dict:
                if covenant_dict["max"]:
                    covenant_dict["max"] = max(
                        convert_increase_to_double(value[1].increase), covenant_dict.get("max"))
                else:
                    covenant_dict["max"] = convert_increase_to_double(
                        value[1].increase)

                if covenant_dict["min"]:
                    covenant_dict["min"] = min(
                        convert_increase_to_double(value[1].increase), covenant_dict.get("min"))
                else:
                    covenant_dict["min"] = convert_increase_to_double(
                        value[1].increase)
        # use that data to build out the sim_type data block by covenant
        results[sim_type.lower()] = covenants
    # output 1 JSON file per talent setup as Results_Aggregate_am-as.json
    chart_data = {
        "name": "Aggregate {0}".format(talents),
        "data": results,
        "last_updated": datetime.now().strftime("%Y-%m-%d")
    }
    json_data = json.dumps(chart_data)
    output_file = "results/Results_Aggregate_{0}.json".format(talents)
    with open(output_file, 'w') as results_json:
        results_json.write(json_data)


def build_covenant_json():
    sim_types = ["Composite", "Dungeons", "Single"]
    talents = config["builds"].keys()
    results = {}
    # find the 3 JSON entries for each talent setup
    for sim_type in sim_types:
        covenants = {
            "kyrian": {"max": 0.00, "min": 0.00},
            "necrolord": {"max": 0.00, "min": 0.00},
            "night_fae": {"max": 0.00, "min": 0.00},
            "venthyr": {"max": 0.00, "min": 0.00}
        }
        # loop over config["builds"] to get each set of covenant{} data
        for talent in talents:
            input_file = "results/Results_Aggregate_{0}.json".format(talent)
            with open(input_file) as data:
                talent_data = json.load(data)
            covenant_data = talent_data['data'][sim_type.lower()]
            # for each set of covenant{} data populate new dict with min/max
            for covenant in covenants.keys():
                if covenants[covenant]["max"]:
                    covenants[covenant]["max"] = max(covenant_data[covenant]["max"], covenants[covenant]["max"])
                else:
                    covenants[covenant]["max"] = covenant_data[covenant]["max"]

                if covenants[covenant]["min"]:
                    covenants[covenant]["min"] = min(covenant_data[covenant]["min"], covenants[covenant]["min"])
                else:
                    covenants[covenant]["min"] = covenant_data[covenant]["min"]
        # output 1 JSON file as Results_Aggregate.json
        results[sim_type.lower()] = covenants
    chart_data = {
        "name": "Aggregate",
        "data": results,
        "last_updated": datetime.now().strftime("%Y-%m-%d")
    }
    json_data = json.dumps(chart_data)
    output_file = "results/Results_Aggregate.json"
    with open(output_file, 'w') as results_json:
        results_json.write(json_data)
            
            
            
            


def get_simc_dir(talent, covenant, folder_name):
    if covenant:
        return "{0}/{1}/{2}/".format(folder_name, talent, covenant)
    elif talent:
        return "{0}/{1}/".format(folder_name, talent)
    else:
        return "{0}/".format(folder_name)


def analyze(talents, directory, dungeons, weights, timestamp, covenant):
    foldername = os.path.basename(os.getcwd())
    # Move to correct outer folder
    while foldername != directory[:-1]:
        os.chdir("..")
        foldername = os.path.basename(os.getcwd())
    csv = "{0}statweights.csv".format(
        get_simc_dir(talents, covenant, 'output'))

    if weights:
        data = pandas.read_csv(csv,
                               usecols=['profile', 'actor', 'DD', 'DPS', 'int', 'haste', 'crit', 'mastery', 'vers'])
    else:
        data = pandas.read_csv(csv, usecols=['profile', 'actor', 'DD', 'DPS'])

    talent_string = "_{0}".format(talents) if talents else ""
    covenant_string = "_{0}".format(covenant) if covenant else ""
    sim_types = ["Dungeons"] if dungeons else ["Composite", "Single"]
    covenant_range = config["sims"][directory[:-1]
                                    ]["steps"][0] == "CovenantRange"

    for sim_type in sim_types:
        results = build_results(data, weights, sim_type, directory)
        base_dps = results.get('Base')
        if config["analyze"]["markdown"]:
            build_markdown(sim_type, talent_string, results,
                           weights, base_dps, covenant_string)
        if config["analyze"]["csv"]:
            build_csv(sim_type, talent_string, results,
                      weights, base_dps, covenant_string)
        # If covenant_range is true we skip building the json here to do it later
        if config["analyze"]["json"] and not covenant_range:
            build_json(sim_type, talent_string, results,
                       directory, timestamp, covenant_string)
    # Check if we need to build extra JSON files
    if covenant_range:
        build_talented_covenant_json(talents)
        build_covenant_json()
    os.chdir("..")
