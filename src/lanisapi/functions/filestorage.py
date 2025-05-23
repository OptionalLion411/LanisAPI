"""This script includes classes and functions about 'Dateispeicher' page."""
import datetime
from urllib.parse import urlencode

import httpx
from attrs import define, field
from selectolax.parser import HTMLParser

from ..constants import URL, headers
from ..helpers.request import Request
from ..helpers.util import convert_size_unit

@define
class SearchResult:
    id: int = field()
    text: str = field()
    ordner: int = field()

@define
class FileNode:
    name: str = field()
    id: int = field()
    download_url: str = field()
    size: str = field()
    last_modified: datetime.datetime = field()
    hint: str|None = field(default=None)
    folder_id: int|None = field(default=None)

@define
class FolderNode:
    name: str = field()
    description: str = field()
    id: int = field()
    subfolder_count: int = field(default=0)



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
            description=description
        ))

    return files, folders

def _download_node(node_id: int|FileNode = 0):
    if isinstance(node_id, FileNode):
        node_id = node_id.id
    stream = Request.client.stream("get", URL.file_storage, params={
        "a": "download",
        "f": node_id
    }, headers=headers)
    return stream
