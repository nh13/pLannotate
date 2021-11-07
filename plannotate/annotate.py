import os
import subprocess
from tempfile import NamedTemporaryFile

from Bio.Seq import Seq
from Bio import SeqIO
from Bio.SeqRecord import SeqRecord
import numpy as np
import pandas as pd
import streamlit as st

import plannotate.resources as rsc
from plannotate.infernal import parse_infernal

log = NamedTemporaryFile()

def BLAST(seq, db):
    task = db['method']
    parameters = db['parameters']
    db_loc = db['db_loc']
    query = NamedTemporaryFile()
    tmp = NamedTemporaryFile()
    SeqIO.write(SeqRecord(Seq(seq), id="temp"), query.name, "fasta")

    if task == "blastn":
        flags = 'qstart qend sseqid sframe pident slen qseq length sstart send qlen evalue'
        #parameters = '-perc_identity 95 -max_target_seqs 20000 -culling_limit 25 -word_size 12'
        subprocess.call( #remove -task blastn-short?
            (f'blastn -task blastn-short -query {query.name} -out {tmp.name} ' #pi needed?
             f'-db {db_loc} {parameters} -outfmt "6 {flags}" >> {log.name} 2>&1'),
            shell=True)

    elif task == "diamond":
        flags = 'qstart qend sseqid pident slen qseq length sstart send qlen evalue'
        #parameters = '-k 0 --min-orf 1 --matrix PAM30 --id 75'
        subprocess.call(f'diamond blastx -d {db_loc} -q {query.name} -o {tmp.name} '
                        f'{parameters} --outfmt 6 {flags} >> {log.name} 2>&1',shell=True)

    elif task == "infernal":
        flags = "--cut_ga --rfam --noali --nohmmonly --fmt 2" #tblout?
        cmd = f"cmscan {flags} --tblout {tmp.name} --clanin {db_loc} {query.name} >> {log.name} 2>&1"
        subprocess.call(cmd, shell=True)
        inDf = parse_infernal(tmp.name)
        
        inDf['qlen'] = len(seq)
        
        #manually gets DNA sequence from seq(x2)
        if not inDf.empty:
            inDf['qseq'] = inDf.apply(lambda x: (seq)[x['qstart']:x['qend']+1].upper(), axis=1)
        
        tmp.close()
        query.close()

        return inDf

    with open(tmp.name, "r") as file_handle:  #opens BLAST file
        align = file_handle.readlines()

    tmp.close()
    query.close()

    inDf = pd.DataFrame([ele.split() for ele in align],columns=flags.split())
    #inDf = inDf.rename(columns = {'qseq':'sseq'}) #for correcting DIAMOND output
    inDf = inDf.apply(pd.to_numeric, errors='ignore')

    return inDf

def calculate(inDf, task, is_linear):

    inDf['qstart'] = inDf['qstart']-1
    inDf['qend']   = inDf['qend']-1

    if task == "blastn":
        inDf['priority'] = 0

    elif task == "diamond":
        try:
            inDf['sseqid'] = inDf['sseqid'].str.split("|", n=2, expand=True)[1]
        except (ValueError, KeyError):
            pass
        inDf['sframe'] = (inDf['qstart']<inDf['qend']).astype(int).replace(0,-1)
        inDf['slen']   = inDf['slen'] * 3
        inDf['length'] = abs(inDf['qend']-inDf['qstart'])+1
        inDf['priority'] = 1

    elif task == "infernal":
        inDf["priority"] = 2
        inDf['qseq'] = ""
        inDf["sframe"] = inDf["sframe"].replace(["-","+"], [-1,1])
        inDf['qstart'] = inDf['qstart']-1
        inDf['qend']   = inDf['qend']-1
        inDf['length'] = abs(inDf['qend']-inDf['qstart'])+1
        inDf['slen'] = abs(inDf['send']-inDf['sstart'])+1
        inDf['pident'] = 100

    inDf = inDf[inDf['evalue'] < 1].copy() #gets rid of "set on copy warning"
    inDf['qstart'], inDf['qend'] = inDf[['qstart','qend']].min(axis=1), inDf[['qstart','qend']].max(axis=1)
    inDf['percmatch']     = (inDf['length'] / inDf['slen']*100)
    inDf['abs percmatch'] = 100 - abs(100 - inDf['percmatch'])#eg changes 102.1->97.9
    inDf['pi_permatch']   = (inDf["pident"] * inDf["abs percmatch"])/100
    inDf['score']         = (inDf['pi_permatch']/100) * inDf["length"]
    inDf['fragment']      = inDf["percmatch"] < 95

    if is_linear == False:
        inDf['qlen']      = (inDf['qlen']/2).astype('int')

    #applies a bonus for anything that is a 100% match to database
    #heurestic! change value maybe
    bonus = 1
    inDf.loc[inDf['pi_permatch']==100, "score"] = inDf.loc[inDf['pi_permatch']==100,'score'] * bonus
    if task == "blastn": #gives edge to nuc database 
        inDf['score']   = inDf['score'] * 1.1

    wiggleSize = 0.15 #this is the percent "trimmed" on either end eg 0.1 == 90%
    inDf['wiggle'] = (inDf['length'] * wiggleSize).astype(int)
    inDf['wstart'] =  inDf['qstart'] + inDf['wiggle']
    inDf['wend']   =  inDf['qend']   - inDf['wiggle']

    return inDf

def clean(inDf):
    #subtracts a full plasLen if longer than tot length
    inDf['qstart_dup'] = inDf['qstart']
    inDf['qend_dup']   = inDf['qend']
    inDf['qstart'] = np.where(inDf['qstart'] >= inDf['qlen'], inDf['qstart'] - inDf['qlen'], inDf['qstart'])
    inDf['qend']   = np.where(inDf['qend']   >= inDf['qlen'], inDf['qend']   - inDf['qlen'], inDf['qend'])

    inDf['wstart'] = np.where(inDf['wstart'] >= inDf['qlen'], inDf['wstart'] - inDf['qlen'], inDf['wstart'])
    inDf['wend']   = np.where(inDf['wend']   >= inDf['qlen'], inDf['wend']   - inDf['qlen'], inDf['wend'])

    inDf=inDf.drop_duplicates()
    inDf=inDf.reset_index(drop=True)

    #st.write("raw", inDf)

    #inDf=calc_level(inDf)

    #create a conceptual sequence space
    seqSpace=[]
    end    = int(inDf['qlen'][0])

    # for some reason some int columns are behaving as floats -- this converts them
    inDf = inDf.apply(pd.to_numeric, errors='ignore', downcast = "integer")

    for i in inDf.index:
        #end    = inDf['qlen'][0]
        wstart = inDf.loc[i]['wstart'] #changed from qstart
        wend   = inDf.loc[i]['wend']   #changed from qend

        sseqid = [inDf.loc[i]['sseqid']]

        if wend < wstart: # if hit crosses ori
            left   = (wend + 1)          * [inDf.loc[i]['kind']]
            center = (wstart - wend - 1) * [None]
            right  = (end  - wstart + 0) * [inDf.loc[i]['kind']]
        else: # if normal
            left   =  wstart             * [None]
            center = (wend - wstart + 1) * [inDf.loc[i]['kind']]
            right  = (end  - wend   - 1) * [None]

        seqSpace.append(sseqid+left+center+right) #index, not append

    seqSpace=pd.DataFrame(seqSpace,columns=['sseqid'] + list(range(0, end)))
    seqSpace=seqSpace.set_index([seqSpace.index, 'sseqid']) #multi-indexed
    #filter through overlaps in sequence space
    toDrop=set()
    for i in range(len(seqSpace)):

        if seqSpace.iloc[i].name in toDrop:
            continue #need to test speed

        end    = inDf['qlen'][0] #redundant, but more readable
        qstart = inDf.loc[seqSpace.iloc[i].name[0]]['qstart']
        qend   = inDf.loc[seqSpace.iloc[i].name[0]]['qend']
        kind   = inDf.loc[seqSpace.iloc[i].name[0]]['kind']

        #columnSlice=seqSpace.columns[(seqSpace.iloc[i]==1)] #only columns of hit
        if qstart < qend:
            columnSlice = list(range(qstart+1, qend + 1))
        else:
            columnSlice = list(range(0,qend + 1)) + list(range(qstart, end))
        
        rowSlice = (seqSpace[columnSlice] == kind).any(1) #only the rows that are in the columns of hit
        toDrop   = toDrop | set(seqSpace[rowSlice].loc[i+1:].index) #add the indexs below the current to the drop-set

    ####### For keeping 100% matches
    # keep = inDf[inDf['pi_permatch']==100]
    # keep = set(zip(keep.index, keep['sseqid']))
    # st.write(keep)
    # toDrop = toDrop - keep

    seqSpace = seqSpace.drop(toDrop)
    inDf = inDf.loc[seqSpace.index.get_level_values(0)] #needs shared index labels to work
    inDf = inDf.reset_index(drop=True)
    # may need to run this with df that "passes" the origin

    return inDf


#@st.cache(hash_funcs={pd.DataFrame: lambda _: None}, suppress_st_warning=True)
def annotate(inSeq, blast_database, linear = False, is_detailed = False):

    progressBar = st.progress(0)
    progress_amt = 5
    progressBar.progress(progress_amt)

    #This catches errors in sequence via Biopython
    fileloc = NamedTemporaryFile()
    SeqIO.write(SeqRecord(Seq(inSeq),name="pLannotate",annotations={"molecule_type": "DNA"}), fileloc.name, 'fasta')
    record=list(SeqIO.parse(fileloc.name, "fasta"))
    fileloc.close()

    record=record[0]

    # doubles sequence for origin crossing hits
    if linear == False:
        query = str(record.seq) + str(record.seq)
    elif linear == True:
        query = str(record.seq)
    else:
        progressBar.empty()
        st.error("error")
        return pd.DataFrame()

    databases = rsc.get_yaml(blast_database)
    increment = int(90 / len(databases))
    
    raw_hits = []
    for database_name in databases:
        database = databases[database_name]
        hits = BLAST(seq = query, db = database)
        hits = calculate(hits, task = database['method'], is_linear = linear)
        hits['db'] = database_name
        hits['sseqid'] = hits['sseqid'].astype(str)
       
        if is_detailed == True:
            details = database['details']
            try:
                hits['kind'] = details['default_type']
            except KeyError:
                if details['file'] == True:
                    details_file_loc = rsc.get_details(database_name) + ".csv"
                    featDesc=pd.read_csv(details_file_loc)[["sseqid","Type"]]
                    featDesc = featDesc.rename(columns={"Type": "kind"})
                    featDesc['sseqid'] = featDesc['sseqid'].astype(str)

                    hits = hits.merge(featDesc, on='sseqid', how='left')
            #hits['kind'] = inDf.apply(lambda row : get_types(row, hits['details']), axis=1)
        else:
            hits['kind'] = 1
                
        raw_hits.append(hits)
        
        progress_amt += increment
        progressBar.progress(progress_amt)
        
    
    blastDf = pd.concat(raw_hits)
    
    blastDf = blastDf.sort_values(by=["score","length","percmatch"], ascending=[False, False, False])

    progressBar.empty()
    
    if blastDf.empty: #if no hits are found
        return blastDf

    blastDf = clean(blastDf)
    
    if blastDf.empty: #if no hits are found
        return blastDf

    blastDf['qend'] = blastDf['qend'] + 1 #corrects position for gbk

    #manually gets DNA sequence from inSeq
    #blastDf['qseq'] = inSeq #adds the sequence to the df
    #blastDf['qseq'] = blastDf.apply(lambda x: x['qseq'][x['qstart']:x['qend']+1], axis=1)
    blastDf['qseq'] = blastDf.apply(lambda x: str(Seq(x['qseq']).reverse_complement()) if x['sframe'] == -1 else x['qseq'], axis=1)

    #blastDf = blastDf.append(orfs)

    global log
    log.close()
    
    # drop poor matches that are very small fragments
    # usually an artifact from wonky SnapGene features that are composite features
    blastDf = blastDf.loc[blastDf['pi_permatch'] > 3]

    return blastDf

