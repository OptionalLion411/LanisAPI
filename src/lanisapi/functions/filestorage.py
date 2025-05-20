"""This script includes classes and functions about 'Dateispeicher' page."""
import datetime
from urllib.parse import urlencode

from attrs import define, field
from selectolax.parser import HTMLParser

from ..constants import URL, headers
from ..helpers.request import Request
from ..helpers.util import convert_size_unit

@define
class SearchResult:
    id: field(type=int)
    text: field(type=str)
    ordner: field(type=int)

@define
class FileNode:
    name: field(type=str)
    id: field(type=int)
    folder_id: field(type=int|None, default=None)
    download_url: field(type=str)
    size: field(type=str)
    last_modified: field(type=datetime.datetime)
    hint: field(type=str|None, default=None)

@define
class FolderNode:
    name: field(type=str)
    description: field(type=str)
    id: field(type=int)
    subfolder_count: field(type=int, default=0)



def _search(query: str = "") -> list[SearchResult]:
    response = Request.get(URL.file_storage, params={
        "q": query, "a": "searchFiles"
    }, headers=headers)

    res = []
    if response.status_code == 200:
        for i in response.json()[0]:
            res.append(SearchResult(
                id=int(i["id"]),
                text=i["text"],
                ordner=int(i["ordner"])
            ))

    return res

def _list_node(node_id: int = 0) -> tuple[list[FileNode], list[FolderNode]]:
    response = Request.get(URL.file_storage, params={
        "a": "view",
        "folder": node_id
    })
    html = HTMLParser(response.text)

    files = []
    for i in html.css("table#files tbody tr"):
        fields = i.css("td")
        file_id = int(i.attributes["data-id"].strip())
        files.append(FileNode(
            name=fields[2].text().strip(),
            id=file_id,
            download_url=URL.file_storage + "?" + urlencode({"a": "download", "f": file_id}),
            size=convert_size_unit(fields[4].text().strip()),
            last_modified=datetime.datetime.strptime(fields[3].text().strip(), "%d.%m.%Y %H:%M:%S"),
            folder_id=node_id,
            hint=""
        ))
    folders = []
    for i in html.css(".folder"):
        folder_id = int(i.attributes["data-id"].strip())
        name = i.css_first(".caption").text().strip()
        description = i.css_first(".desc").text().strip()
        # subfolders = i.css_first("[title='Anzahl Ordner']").text().strip() # could be used for count of subfolders
        folders.append(FolderNode(
            name=name,
            id=folder_id,
            description=description,
            subfolder_count=None
        ))

    return files, folders

def _download_node(node_id: int|FileNode = 0):
    if isinstance(node_id, FileNode):
        node_id = node_id.id
    response = Request.get(URL.file_storage, params={
        "a": "download",
        "f": node_id
    }, headers=headers)
    return response.content
