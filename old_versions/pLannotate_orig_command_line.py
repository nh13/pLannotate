#!/usr/bin/env python
# coding: utf-8

import argparse
from Bio.Seq import Seq
from Bio import SeqIO
from Bio.SeqRecord import SeqRecord
import subprocess
from Bio.SeqFeature import SeqFeature, FeatureLocation
from Bio.Alphabet import generic_dna
from tempfile import NamedTemporaryFile
import pandas as pd

#import time ######
#start_time = time.time() #######

def bash(inCommand, autoOutfile = False):
    if autoOutfile == True:
        tmp = NamedTemporaryFile()
        subprocess.call(inCommand +' > '+tmp.name, shell=True)
        f = open(tmp.name,'r')
        tmp.close()
        return(f.read())
    else:
        subprocess.call(inCommand, shell=True)
def BLAST(seq,wordsize=12, db='nr_db', BLASTtype="p", flags = 'sseqid pident qstart qend sseq slen send sstart'):

    query = NamedTemporaryFile()
    SeqIO.write(SeqRecord(Seq(seq), id="temp"), query.name, "fasta")
    tmp = NamedTemporaryFile()
    bash(
        'blast'+BLASTtype+' -task blastn-short -query ' + query.name + ' -out ' + tmp.name +
        ' -db ' + db +
        ' -max_target_seqs 20000 -word_size '+str(wordsize)+' -outfmt "6 '+flags+'"')
    with open(tmp.name, "r") as file_handle:  #opens BLAST file
        align = file_handle.readlines()

    tmp.close()
    query.close()
    return align
def set_intersection(listOfSublists):
    #takes a list of sublists and returns a list of all common elements in sublist
    result = set(listOfSublists[0])
    for s in listOfSublists[1:]:
        result.intersection_update(s)
    return list(result)
def get_hits(inHits):
    df = []

    for ele in inHits:
        splitAlign=ele.split()

        qstart = int(splitAlign[0])-1
        qend = int(splitAlign[1])-1
        sframe = int(splitAlign[3])
        pident = float(splitAlign[4])
        slen = int(splitAlign[5])
        sseq = splitAlign[6]
        percmatch = round((len(sseq)/slen)*100,3)

        sseqid = splitAlign[2]
        partType=sseqid.split("|")[1]
        sseqid=sseqid.split("|")[0]
        name = sseqid.split(".gb")[0].replace("_"," ")#.split(" (")[0]

        abspercmatch=100-abs(100-percmatch)#eg changes 102.1->97.9

        absdiff=(pident/100)*(abspercmatch/100)*len(sseq)
        df.append({'Abs. diff': absdiff, 'name': name,'type':partType,'start':qstart,'end':qend,'frame':sframe, 'percent identity': pident, 'percent match': abspercmatch, "Length of hit":len(sseq),"Length of target seq":slen} )
    df=pd.DataFrame(df)
    df=df.sort_values(by=["Abs. diff","Length of hit",'percent match'], ascending=[False, False, False])
    chunk=df[df["type"]=='source']
    #df=df[df["type"]!='source']

    return df,chunk
def annotate(fileloc,outfileloc="", fragmentMode=True, csv=False):
    try:
        assert outfileloc != "","no outfile path given"
        assert outfileloc[-4:]==".gbk","outfile must end in .gbk!"
    except IndexError:
        raise NameError('outpath not correctly formatted')

    database="./BLAST_dbs/full_snapgene_feature_list_w_types_db"

    recordDf=pd.DataFrame()
    wiggle=6 #maybe change to a percentage of overlap instead of absolute bps?
            #this also can through lists out of index in the current way it works

    record=list(SeqIO.parse(fileloc, "fasta"))
    assert len(record)==1,f"FASTA file contains ~multitudes~ --> skipping {fileloc}"
    record=record[0]
    record.name=fileloc.split("/")[-1].split(".")[0]
    record.seq.alphabet=generic_dna
    record.annotations["topology"] = "circular"
    query=str(record.seq)*2
    pLen = len(str(record.seq))

    seqSpace=[[] for i in range(len(query))]
    #first annotates full small features, 12-25 nts
    hits,chunk = get_hits(BLAST(seq=query,wordsize=12, db =database,BLASTtype="n",flags='qstart qend sseqid sframe pident slen sseq'))
    for ele in hits.index:
        slen=int(hits.loc[[ele]]['Length of target seq'])

        if slen < 25:
            qstart = int(hits.loc[[ele]]['start'])
            qend = int(hits.loc[[ele]]['end'])
            sframe = int(hits.loc[[ele]]['frame'])
            pident = float(hits.loc[[ele]]['percent identity'])
            percmatch = float(hits.loc[[ele]]['percent match'])
            name = hits.loc[[ele]]['name'].values[0]
            partType=hits.loc[[ele]]['type'].values[0]

            #if pident==100 and percmatch==100: #filters out all other hits
            if pident >= ((slen-1)/slen)*100: #filters out all other hits
                if percmatch >= ((slen-1)/slen)*100: #length of match

                    if qend-pLen>0 and qstart-pLen>=0:
                        continue
                    elif qend-pLen>0 and qstart-pLen<=0:
                        first=FeatureLocation(qstart, pLen,sframe)
                        second=FeatureLocation(0, qend-pLen+1,sframe)
                        if sframe == 1 or sframe == 0:
                            featLoc=first+second
                        elif sframe == -1:
                            featLoc=second+first
                        else:
                            print("error1.1")
                    elif qend<=pLen and qstart<=pLen:
                        featLoc=FeatureLocation(qstart, qend+1,sframe)
                    else:
                        print("error1.2")

                    record.features.append(SeqFeature(featLoc, type=partType,qualifiers={"label": name,"identity":pident,"match length":percmatch, "Other:":partType}))
                    recordDf=recordDf.append(hits.loc[[ele]])

                    for i in featLoc:
                        seqSpace[i].append((name,sframe,pident,percmatch))
                        if len(featLoc.parts) > 1:
                            seqSpace[i+len(record.seq)].append((name,sframe,pident,percmatch))

    hits,chunk = get_hits(BLAST(seq=query,wordsize=18, db =database,BLASTtype="n",flags='qstart qend sseqid sframe pident slen sseq'))
    for ele in hits.index:
        qstart = int(hits.loc[[ele]]['start'])
        qend = int(hits.loc[[ele]]['end'])

        occupiedSpace=set_intersection(seqSpace[  qstart+wiggle:qend-(wiggle-1)])

        if not occupiedSpace:
            name = hits.loc[[ele]]['name'].values[0]
            sframe = int(hits.loc[[ele]]['frame'])
            pident = float(hits.loc[[ele]]['percent identity'])
            percmatch = float(hits.loc[[ele]]['percent match'])
            partType=hits.loc[[ele]]['type'].values[0]

            if pident>=95: #filters out all other hits

                if qend-pLen>0 and qstart-pLen>=0:
                    continue
                elif qend-pLen>0 and qstart-pLen<=0:
                    first=FeatureLocation(qstart,pLen,sframe)
                    second=FeatureLocation(0, qend-pLen+1,sframe)
                    if sframe == 1 or sframe == 0:
                        featLoc=first+second
                    elif sframe == -1:
                        featLoc=second+first
                    else:
                        print("error2.1")
                elif qend<=pLen and qstart<=pLen:
                    featLoc=FeatureLocation(qstart, qend+1,sframe)
                else:
                    print("error2.2")

                if percmatch < 95: #length of match
                    Type="Fragment"
                else:
                    Type=str(partType)

                for i in featLoc:
                    seqSpace[i].append((name,sframe,pident,percmatch))
                    if len(featLoc.parts) > 1:
                        seqSpace[i+len(record.seq)].append((name,sframe,pident,percmatch))

                #if name != "ColE1 ori chunk":
                record.features.append(SeqFeature(featLoc, type=Type,qualifiers={"label": name,"identity":pident,"match length":percmatch, "Other:":partType}))
                recordDf=recordDf.append(hits.loc[[ele]])

    record.name=record.name[:20].replace(" ","_")#######maybe change this

    if fragmentMode == False:
    	wholeFeats=[]
    	for feat in record.features:
    		if feat.type != "Fragment" or feat.qualifiers['label'] == "ColE1 ori chunk":
    			wholeFeats.append(feat)
    	record.features=wholeFeats

    with open(outfileloc, "w") as handle:
        SeqIO.write(record, handle, "genbank")
    print("gbk written")

    if csv == True:
    	recordDf.sort_values(by=["Abs. diff"],ascending=[False])
    	recordDf.to_csv(f"{outfileloc.split('.gbk')[0]}.csv")
    	print("csv written")

###

parser = argparse.ArgumentParser(description='Annotates engineered plasmid sequences ')
parser.add_argument('-i','--infile', help='location of input FASTA file', required=True)
parser.add_argument('-o','--outfile', help='output file location for .gbk (must end in .gbk)', required=True)
parser.add_argument('-f','--frag', help="toggles fragment annotation", default=False, action='store_true',required=False)
parser.add_argument('-c','--csv', help="also writes a csv file of annotations in same output location as gbk", default=False, action='store_true',required=False)


args = parser.parse_args()

annotate(args.infile,args.outfile,args.frag,args.csv)
#print("--- %s seconds ---" % (time.time() - start_time))##########