import argparse
from datetime import date
import json

import numpy as np
import pandas as pd
import plotly.express as px
import pyvo
import requests


number_catalogs = "number of catalogues"
journal_names_json_file = "journal_names.json"


def query_vizier_for_metadata_of_catalogs():
    """Query the metadata catalogue from VizieR.

    It returns it as a pandas DataFrame
    """
    tap_vizier = pyvo.dal.TAPService("https://tapvizier.cds.unistra.fr/TAPVizieR/tap/")
    query_meta_catalogs = """
                          SELECT * FROM METAcat
                          WHERE catid >1
                          """
    meta_catalogs = tap_vizier.search(query_meta_catalogs)
    return meta_catalogs.to_table().to_pandas()


def get_count_for_journals(metadata, cut: int):
    """Clean data and export count per journal.

    Arguments
    ---------

    cut (int, optional): Cut for the minimal number of catalogues to
                         appear in the graph. Defaults to 50.

    Returns
    -------
        int: total number of catalogues
    """

    # cleaning steps
    journal_code = [
        bibcode[4:].split(".")[0] for bibcode in np.array(metadata["bibcode"])
    ]
    journal_code = [code.replace("+", "&") for code in journal_code]
    journal_code = [code.split("(")[0] for code in journal_code]

    # add column with the counts
    metadata[number_catalogs] = journal_code

    # proceeds the groupby
    count_journal = metadata.groupby(journal_code).count()
    count_journal.reset_index(inplace=True)
    count_journal = count_journal[["index", number_catalogs]]
    count_journal.loc[
        (count_journal[number_catalogs] < cut) | (count_journal["index"] == ""), "index"
    ] = "other"

    # exports the counts per journal after groupby
    count_per_journal = count_journal.groupby("index").sum("journal_code")
    count_per_journal.reset_index(inplace=True)

    return count_per_journal


def get_dict_of_journals_names(count_per_journal, ads_api_key: str):
    """Query the journal names corresponding to bibcodes.

    This is done by scanning the `index` column of `count_per_journal.csv`
    and if one entry is missing in `journal_names.json` it will fetch the
    value through the ADS API.

    Args:
        ads_api_key (str): API key to connect to ADS
    """

    ads_api_adress = "https://api.adsabs.harvard.edu/v1/journals/summary/"

    # open journal names data files
    with open(journal_names_json_file) as json_data:
        current_list = json.load(json_data)

    updated = False
    # scans through the journal short names
    for index in count_per_journal["index"]:
        if (
            (index not in current_list.keys())
            and isinstance(index, str)
            and index != "other"
        ):
            print("add index", index)

            # access to the ADS API here
            result = requests.get(
                ads_api_adress + index,
                headers={"Authorization": "Bearer " + ads_api_key},
            )
            if result.status_code == 200:
                journal_name = result.json()["summary"]["master"]["journal_name"]
                current_list.update({index: journal_name})
                updated = True
            else:
                raise Warning(f"request status code: {result.status_code}")

    # saves the new current_list if it changed
    if updated:
        with open(journal_names_json_file, "w") as file:
            json.dump(current_list, file, indent=2)


def plot_pie_chart(today: str, number_of_catalogs: int, count_per_journal, cut):
    """Plot a pie chart for the catalogues provenance in VizieR.

    Args:
        today (str): the date of today
        number_of_catalogs (int): total number of catalogues, as of today
    """
    # import the data
    with open(journal_names_json_file) as json_data:
        journal_names = json.load(json_data)
    journal_names.update({"other": f"journals with less than {cut} catalogues"})

    # join the dataframe and the dictionnary
    count_per_journal["sub journal name"] = count_per_journal["index"].map(journal_names)

    # create column for journal families 
    principal_journal = {
        "Astronomy and Astrophysics": "Astronomy & Astrophysics Journals",
        "Astronomy and Astrophysics Supplement Series": "Astronomy & Astrophysics Journals",
        "The Astronomical Journal": "American Astronomical Society Journals",
        "The Astrophysical Journal": "American Astronomical Society Journals",
        "The Astrophysical Journal Supplement Series": "American Astronomical Society Journals",
    }
    count_per_journal["journal name"] = count_per_journal["sub journal name"].replace(principal_journal)
    count_per_journal.loc[count_per_journal["sub journal name"] == count_per_journal["journal name"], ["sub journal name"]] = np.nan
    
    # and now plot time!
    fig = px.sunburst(
        count_per_journal,
        values="number of catalogues",
        path=["journal name", "sub journal name"],
        title=f"Provenance of the {number_of_catalogs} catalogues in VizieR ({today})",
        color_discrete_sequence=px.colors.qualitative.Pastel,
    )

    invert_journal_names = {v: k for k, v in journal_names.items()}
    invert_journal_names.update({"American Astronomical Society Journals": "AAS Journals", "Astronomy & Astrophysics Journals": "A&A Journals"})

    fig.update_traces(hovertemplate='<b>%{label}</b><br>Number of catalogues: %{value}')  # parent, or label, or id, or value
    print(fig.data[0])
    
    short_label = np.array([invert_journal_names[label] for label in fig.data[0]["labels"] ], dtype=object)

    fig.update_traces(texttemplate="<b>" + short_label + "</b><br>%{percentEntry}")
    fig.update_traces(legendrank=100, selector=dict(type='sunburst'))
    fig.update_layout(margin = dict(t=50, l=0, r=0, b=0))
    fig.write_html("index.html")


def main(ads_api_key):
    # queries VizieR for its metadata catalog
    metadata = query_vizier_for_metadata_of_catalogs()
    #metadata.to_pickle("metadata.pkl")
    #metadata = pd.read_pickle("metadata.pkl")
    # number of records today
    todays_number_of_catalogs = len(metadata)
    # threshold on number of catalogs from a same journal
    # only keep above cut
    cut = 250
    # a dataframe containing journal short id and corresponding catalog count
    counts_per_journals = get_count_for_journals(metadata, cut)
    # updates the list of journal names if needed by querying the ADS API
    get_dict_of_journals_names(counts_per_journals, ads_api_key)
    # saves the plot as html
    plot_pie_chart(
        date.today().isoformat(), todays_number_of_catalogs, counts_per_journals, cut
    )


if __name__ == "__main__":
    # add the API argument
    parser = argparse.ArgumentParser()
    parser.add_argument("api", help="api key to connect to ADS", type=str)
    arguments = parser.parse_args()
    # call main
    main(arguments.api)
