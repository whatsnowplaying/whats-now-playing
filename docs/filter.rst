Filter
======

Some DJ Pools add extra identifiers to track titles.  Now Playing has the ability to remove
extra text from the title of a track using
`Python-style regular expressions <https://docs.python.org/3/howto/regex.html>`_ .

Clicking on the 'Add Recommended' button will add rules that remove the following:

* ' (Clean)', ' (clean)', and all other variations of case like ' (ClEaN)'
* At the end of the line: ' - clean', ' - Clean' and similarly is case insensitive
* ' [Clean]' and ' [clean]' and smiliarly is case insensitive

They will also remove the same types of variations of:

* explicit
* dirty
* official music video

More explicit rules may be added by:

1. Click the Add Entry button
2. Click on the 'new' entry
3. Edit to be a regular expression

To delete an existing entry:

1. Select the entry in the list
2. Click Delete Entry

The order in which the rules are applied are done in the same order as presented in
the list.  To change the order, select the entry and drag it to the location in the
list.
